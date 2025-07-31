# Copyright 2017 Autodesk, Inc.  All rights reserved.
#
# Use of this software is subject to the terms of the Autodesk license agreement
# provided at the time of installation or download, or which otherwise accompanies
# this software in either electronic or hard copy form.
#

# See docs folder for detailed usage info.

import os
import pytz
import shotgun_api3


def registerCallbacks(reg):
    """
    Register our callbacks.

    :param reg: A Registrar instance provided by the event loop handler.
    """

    # Grab authentication env vars for this plugin. Install these into the env
    # if they don't already exist.
    server = os.environ["SG_SERVER"]
    script_name = os.environ["SGDAEMON_VERSIONFINALED_NAME"]
    script_key = os.environ["SGDAEMON_VERSIONFINALED_KEY"]

    args = {
        "version_status_field": "sg_status_list",
        "query_statuses": ["fna"],
        "target_entity_type": "Shot",
        "target_status_field": "sg_vfx_status",
        "target_status": "Final Approved",
        "superseded_status": "",
        "version_date_field": "client_approved_at",
        "target_date_field": "",
        "linked_version_field": "",
        "timezone": "America/New_York",
    }

    # Grab an sg connection for the validator.
    sg = shotgun_api3.Shotgun(server, script_name=script_name, api_key=script_key)

    # Bail if our validator fails.
    if not is_valid(sg, reg.logger, args):
        reg.logger.warning("Plugin is not valid, will not register callback.")
        return

    reg.registerCallback(
        script_name,
        script_key,
        version_finaled,
        {"Shotgun_Version_Change": args["version_status_field"]},
        args,
    )
    reg.logger.debug("Registered callback.")


def is_valid(sg, logger, args):
    """
    Validate our args.

    :param sg: Shotgun API handle.
    :param logger: Logger instance.
    :param args: Any additional misc arguments passed through this plugin.
    :returns: True if plugin is valid, None if not.
    """

    return True


def version_finaled(sg, logger, event, args):
    """
    Handles the logic to final a Version and update the target entity.

    :param logger: Logging object.
    :param event: Event object.
    :param args: Any args that can be passed in from the callback.
    """

    # Return if we don't have all the field values we need.
    if not event.get("meta", {}).get("entity_id"):
        return

    # Make some vars for convenience.
    entity_id = event["meta"]["entity_id"]

    # Re-query the Version to get necessary field values.
    version = sg.find_one(
        "Version",
        [["id", "is", entity_id]],
        ["code", "entity", args["version_status_field"]],
    )

    # Return if we can't find the Version.
    if not version:
        logger.debug("Could not find Version with id %s, skipping." % entity_id)
        return

    # Return if the Version status is not in the query_statuses list.
    if (
        args.get("query_statuses")
        and version[args["version_status_field"]] not in args["query_statuses"]
    ):
        logger.debug(
            'Ignoring %s, status "%s" is not of allowed type(s): %s.'
            % (
                version["code"],
                version[args["version_status_field"]],
                args["query_statuses"],
            )
        )
        return

    # Return if the Version isn't linked to an entity of target_entity_type.
    if (
        not version.get("entity")
        or not version["entity"].get("name")
        or not version["entity"].get("id")
        or version["entity"].get("type") != args["target_entity_type"]
    ):
        logger.debug(
            "Ignoring %s, not linked to a %s."
            % (version.get("code"), args["target_entity_type"])
        )
        return

    # Gather the date or timestamp data appropriate for the date field types of
    # both the Version and target entity.
    version_date_or_timestamp = get_date_or_timestamp(
        logger,
        sg,
        event,
        "Version",
        args.get("version_date_field"),
        args.get("timezone"),
    )
    target_date_or_timestamp = get_date_or_timestamp(
        logger,
        sg,
        event,
        args["target_entity_type"],
        args.get("target_date_field"),
        args.get("timezone"),
    )

    # If the target_status value is not set, use the Value set on the Version's
    # status field.
    if args.get("target_status"):
        target_status = args["target_status"]
    else:
        target_status = version[args["version_status_field"]]

    # Init a list for a batch call to the Shotgun API.
    batch_data = []

    # Assemble our Version update data based on what's available.
    data = {}
    if args.get("target_status_field"):
        data[
            "entity.%s.%s" % (args["target_entity_type"], args["target_status_field"])
        ] = target_status
    if version_date_or_timestamp:
        data[args["version_date_field"]] = version_date_or_timestamp
    if target_date_or_timestamp:
        data[
            "entity.%s.%s" % (args["target_entity_type"], args["target_date_field"])
        ] = target_date_or_timestamp

    # Update the Version.
    if data:
        batch_data.append(
            {
                "request_type": "update",
                "entity_type": "Version",
                "entity_id": version["id"],
                "data": data,
            }
        )

    # Update the target entity.
    # Note: it is not possible to update a linked entity field from the entity
    # it is being linked to, otherwise we could do this from the Version.
    if args.get("linked_version_field"):
        batch_data.append(
            {
                "request_type": "update",
                "entity_type": args["target_entity_type"],
                "entity_id": version["entity"]["id"],
                "data": {
                    args["linked_version_field"]: {
                        "type": "Version",
                        "id": version.get("id"),
                    }
                },
            }
        )

    # Find all other Versions linked to the target entity and update their
    # statuses, if a superseded_status value has been set and it is not in the
    # query_statuses list (otherwise we'd end up in an infinite loop).
    if args.get("superseded_status") and not args["superseded_status"] in args.get(
        "query_statuses"
    ):
        other_versions = sg.find(
            "Version",
            [["entity", "is", version["entity"]], ["id", "is_not", version["id"]]],
            [args["version_status_field"], args["version_date_field"]],
        )
        if other_versions:
            for other_version in other_versions:
                if (
                    args.get("query_statuses")
                    and other_version[args["version_status_field"]]
                    in args["query_statuses"]
                ):
                    update_dict = {
                        args["version_status_field"]: args["superseded_status"]
                    }
                    if (
                        version_date_or_timestamp
                        and not other_version[args["version_date_field"]]
                    ):
                        update_dict[args["version_date_field"]] = (
                            version_date_or_timestamp
                        )
                    batch_data.append(
                        {
                            "request_type": "update",
                            "entity_type": "Version",
                            "entity_id": other_version["id"],
                            "data": update_dict,
                        }
                    )

    # If we have something to do, then do it.
    if batch_data:
        sg.batch(batch_data)

        # Tell the logger which target entity and Version was updated.
        logger.info(
            "Updated %s %s (%s) and Version %s (%s)."
            % (
                args["target_entity_type"],
                version["entity"]["name"],
                version["entity"]["id"],
                version["code"],
                version["id"],
            )
        )
    else:
        logger.info("Nothing to update.")


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
