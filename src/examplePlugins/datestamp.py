# Copyright 2018 Autodesk, Inc.  All rights reserved.
#
# Use of this software is subject to the terms of the Autodesk license agreement
# provided at the time of installation or download, or which otherwise accompanies
# this software in either electronic or hard copy form.
#

# See docs folder for detailed usage info.

import os
import shotgun_api3
import pytz


def registerCallbacks(reg):
    """
    Register our callbacks.

    :param reg: A Registrar instance provided by the event loop handler.
    """

    # Grab authentication env vars for this plugin. Install these into the env
    # if they don't already exist.
    server = os.environ["SG_SERVER"]
    script_name = os.environ["SGDAEMON_DATESTAMP_NAME"]
    script_key = os.environ["SGDAEMON_DATESTAMP_KEY"]

    # User-defined plugin args, change at will.
    args = {
        "entity_types": ["Shot"],
        "status_field": "sg_status_list",
        "statuses": ["fin"],
        "date_field": "sg_finaled_on",
        "timezone": "US/Pacific",
        "allow_date_overwrite": False,
        "set_date_on_entity_creation": False,
    }

    # Grab an sg connection for the validator.
    sg = shotgun_api3.Shotgun(server, script_name=script_name, api_key=script_key)

    # Bail if our validator fails.
    if not is_valid(sg, reg.logger, args):
        reg.logger.warning("Plugin is not valid, will not register callback.")
        return

    # Build our event_filter.
    event_filter = {}
    for entity_type in args["entity_types"]:

        # If both status_field and statuses are non-empty, add an entity Change
        # event to the match_events dict.
        if args["status_field"] and args["statuses"]:
            event_filter["Shotgun_%s_Change" % entity_type] = [args["status_field"]]

        # If set_date_on_entity_creation is true, add an entity New event to the
        # match_events dict.
        if args["set_date_on_entity_creation"]:
            event_filter["Shotgun_%s_New" % entity_type] = None

    # Register our callback with the Shotgun_%s_Change event and tell the logger
    # about it.
    reg.registerCallback(
        script_name,
        script_key,
        set_datestamp,
        event_filter,
        args,
    )
    reg.logger.debug("Registered callback.")


def check_entity_schema(sg, logger, entity_type, field_name, field_type, values=[]):
    """
    Verifies that field_name of field_type exists in entity_type's schema.

    :param sg: An authenticated Shotgun Python API instance.
    :param logger: Logger instance.
    :param entity_type: String, a Shotgun entity type.
    :param field_name: String, the name of a field on entity_type.
    :param field_type: String, the Shotgun field type field_name should be.
    :param values (optional): List, Status values to validate.
    :returns: True if plugin is valid, None if not.
    """

    # Make sure we can read the schema.
    try:
        entity_schema = sg.schema_field_read(entity_type)
    except Exception as e:
        logger.warning('Can\'t read SG schema for entity "%s": %s' % (entity_type, e))
        return

    # Grab the Shotgun field data type, if the field exists.
    sg_type = entity_schema.get(field_name, {}).get("data_type", {}).get("value")

    # Assume the entity doesn't exist in Shotgun and bail if no data_type value
    # was found.
    if not sg_type:
        logger.warning(
            '%s entity field "%s" does not exist in Shotgun, please fix.'
            % (
                entity_type,
                field_name,
            )
        )
        return

    # Make sure the field is the correct Shotgun type.
    if sg_type not in field_type:
        logger.warning(
            'SG field "%s" is type "%s" but should be of type(s) "%s," please fix.'
            % (field_name, sg_type, field_type)
        )
        return

    # Make sure the field's value is valid.
    for value in values:
        valid_values = entity_schema[field_name]["properties"]["valid_values"]["value"]
        if value not in valid_values:
            logger.warning(
                '%s field "%s" does not accept value "%s", only %s, please fix.'
                % (
                    entity_type,
                    field_name,
                    value,
                    valid_values,
                )
            )
            return

    return True


def is_valid(sg, logger, args):
    """
    Validate our args.

    :param sg: Shotgun API handle.
    :param logger: Logger instance.
    :param args: Any additional misc arguments passed through this plugin.
    :returns: True if plugin is valid, None if not.
    """

    # Verify that the date and status fields exist in each entity schema.
    for entity_type in args["entity_types"]:
        if args["status_field"] and args["statuses"]:
            if not check_entity_schema(
                sg,
                logger,
                entity_type,
                args["status_field"],
                ["list", "status_list"],
                values=args["statuses"],
            ):
                return
        if not check_entity_schema(
            sg,
            logger,
            entity_type,
            args["date_field"],
            ["date_time", "date"],
        ):
            return

    args_to_check = {
        "entity_types": {"type": [list], "allow_empty": False},
        "timezone": {"type": [str], "allow_empty": False},
        "allow_date_overwrite": {"type": [bool], "allow_empty": False},
        "set_date_on_entity_creation": {"type": [bool], "allow_empty": False},
    }

    for name, checks in args_to_check.items():

        # Grab the setting's value type.
        value_type = type(args[name])

        # Make sure the setting value is the correct Python type.
        if value_type not in checks["type"]:
            logger.warning(
                '"%s" setting\'s value is type "%s" but should be type of type(s) "%s," please fix.'
                % (name, value_type, checks["type"])
            )
            return

        if checks["allow_empty"] is not False and not args[name]:
            logger.warning(
                '"%s" setting\'s value is empty but requires a value, please fix.'
                % (name,)
            )
            return

    return True


def set_datestamp(sg, logger, event, args):
    """
    If our entity_type's status field is set to a valid status, set or update
    the date field.

    :param sg: Shotgun API handle.
    :param logger: Logger instance.
    :param event: A Shotgun EventLogEntry entity dictionary.
    :param args: Any additional misc arguments passed through this plugin.
    """

    # Return if we don't have all the field values we need.
    if (
        not event
        or not event.get("meta", {}).get("entity_id")
        or not event.get("entity", {}).get("type")
    ):
        return

    # Make some vars for convenience.
    entity_id = event["meta"]["entity_id"]
    entity_type = event["entity"]["type"]

    # Return if we don't have an entity_New event and the event meta new_value
    # doesn't match the status value.
    if (
        event["event_type"] != "Shotgun_%s_New" % entity_type
        and not event["meta"].get("new_value") in args["statuses"]
    ):
        logger.debug(
            'Status value "%s" doesn\'t match status "%s", skipping.'
            % (event["meta"].get("new_value"), args["statuses"])
        )
        return

    # Return if allow_date_overwrite is False and the date is already set.
    if not args["allow_date_overwrite"]:

        # Re-query the entity to gather extra field values.
        entity = sg.find_one(
            entity_type, [["id", "is", entity_id]], [args["date_field"]]
        )

        # If the date_field value is not empty, return.
        if entity[args["date_field"]]:
            logger.debug(
                "Date is already set (%s): %s. Args prevent overwriting existing values, skipping."
                % (args["date_field"], entity[args["date_field"]])
            )
            return

    # Gather the date or timestamp data appropriate for the date field type.
    date_or_timestamp = get_date_or_timestamp(
        logger,
        sg,
        event,
        entity_type,
        args["date_field"],
        args["timezone"],
    )

    # Update the date field on our entity.
    result = sg.update(
        entity_type,
        entity_id,
        {args["date_field"]: date_or_timestamp},
    )

    logger.info("Updated date: %s." % result)


def get_date_or_timestamp(logger, sg, event, entity_type, date_field, timezone):
    """
    Helper function that determines the date field type on a specified entity
    and returns the date formatted for that type.

    :param logger: Standard logger object.
    :param sg: Shotgun object handle.
    :param event: Daemon event object.
    :param entity_type: String, the type of Shotgun entity, i.e., "Shot".
    :param date_field: String, name of date field.
    :param timezone: String, timezone to use when calculating date/time.
    :returns: date object or timestamp object or None.
    """

    # Determine the date field type of date_field.
    if date_field and timezone:
        date_field_type = sg.schema_field_read(
            entity_type,
            date_field,
        )[date_field][
            "data_type"
        ]["value"]

        # Set the date var type based on the field type.
        date_or_timestamp = event["created_at"].astimezone(pytz.timezone(timezone))
        if date_field_type == "date":
            date_or_timestamp = date_or_timestamp.date()

        logger.debug("Localized Event date or timestamp: %s." % date_or_timestamp)

        return date_or_timestamp
