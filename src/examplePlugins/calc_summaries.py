# Copyright 2018 Autodesk, Inc.  All rights reserved.
#
# Use of this software is subject to the terms of the Autodesk license agreement
# provided at the time of installation or download, or which otherwise accompanies
# this software in either electronic or hard copy form.
#

# See docs folder for detailed usage info.

import os
import shotgun_api3


def registerCallbacks(reg):
    """
    Register our callbacks.

    :param reg: A Registrar instance provided by the event loop handler.
    """

    # Grab authentication env vars for this plugin. Install these into the env
    # if they don't already exist.
    server = os.environ["SG_SERVER"]
    script_name = os.environ["SGDAEMON_CALCSUMMARIES_NAME"]
    script_key = os.environ["SGDAEMON_CALCSUMMARIES_KEY"]

    # Here's the rationale for these wacky defaults:
    # We use project for the link_field because it
    # will always be there. We use id for the Asset and Shot field value
    # because they will always have an id fields. We use Project's
    # sg_description field as the field_to_update value because it's unlikely
    # that field will have been removed.
    args = {
        "field_to_update": "sg_description",
        "link_fields": {
            "Asset": "project",
            "Shot": "project",
        },
        "summarize": [
            {
                "entity_type": "Asset",
                "field": "sg_source_id",
                "sum_or_count": "sum",
                "operator": "+",
                "filters": [],
            },
            {
                "entity_type": "Shot",
                "field": "sg_cut_in",
                "sum_or_count": "sum",
                "operator": "+",
                "filters": [],
            },
        ],
    }

    # Grab an sg connection for the validator.
    sg = shotgun_api3.Shotgun(server, script_name=script_name, api_key=script_key)

    # Bail if our validator fails.
    if not is_valid(sg, reg.logger, args):
        reg.logger.warning("Plugin is not valid, will not register callback.")
        return

    # Init the event filters dict.
    event_filters = {}

    # Add any entity_type/field combos that exist in the summarize list.
    for summary_item in args["summarize"]:
        event_filters["Shotgun_%s_Change" % summary_item["entity_type"]] = summary_item[
            "field"
        ]

    # Register our callback with the Shotgun_%s_Change event and tell the logger
    # about it.
    reg.registerCallback(
        script_name,
        script_key,
        calculate_summaries,
        event_filters,
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

    # Define our check-args list.
    args_to_check = {
        "field_to_update": {"type": [str], "allow_empty": False},
        "link_fields": {"type": [dict], "allow_empty": False},
        "summarize": {"type": [list], "allow_empty": False},
    }

    # Check our args.
    for name, checks in args_to_check.items():

        # Grab the setting's value type.
        value_type = type(args[name])

        # Make sure the setting value is the correct Python type.
        if checks.get("type") and value_type not in checks["type"]:
            logger.warning(
                '"%s" setting\'s value is type "%s" but should be type "%s," please fix.'
                % (name, value_type, checks["type"])
            )
            return

        # Make sure the setting has a non-empty value if allow_empty is False.
        if checks.get("allow_empty") is False and not args[name]:
            logger.warning(
                '"%s" setting\'s value is empty but requires a value, please fix.'
                % (name,)
            )
            return

    # Init a var here so we can check that all entity link_fields point to the
    # same entity type.
    summarize_entity_type = None

    # Loop over our summarize list and check the args in each dict.
    for summary_item in args["summarize"]:

        # Make sure the sum_or_count setting is okay.
        if summary_item["sum_or_count"] not in ["sum", "count"]:
            logger.warning(
                '"sum_or_count" setting must be either "sum" or "count," please fix.'
            )
            return

        # Set valid fields for the summary item field based on the sum_or_count
        # setting. I.e., if we're using count, the field type can be anything.
        valid_fields = None
        if summary_item["sum_or_count"] == "sum":
            valid_fields = ["number", "float", "currency", "percent"]

        # Make sure the field we want to summarize is on our entity.
        if not check_entity_schema(
            sg,
            logger,
            summary_item["entity_type"],
            summary_item["field"],
            valid_fields,
        ):
            return

        # Make sure our operator type is supported.
        operators = ["+", "-", "*", "/"]
        if summary_item["operator"] not in operators:
            logger.warning(
                '"operator" setting must be of type %s, please fix.' % operators
            )
            return

        # Make sure our filters argument is a list.
        if type(summary_item["filters"]).__name__ != "list":
            logger.warning('"filters" value must be a list, please fix.')
            return

        # Make sure our entity type has a link field setting.
        if summary_item["entity_type"] not in args["link_fields"].keys():
            logger.warning(
                '%s is not defined in the "link_fields" setting, please fix.'
                % summary_item["entity_type"]
            )
            return

        # Grab the schema for the linked entity type field.
        link_field_schema = sg.schema_field_read(
            summary_item["entity_type"],
            args["link_fields"][summary_item["entity_type"]],
        )

        # Grab the data type for the linked field.
        data_type = link_field_schema[list(link_field_schema.keys())[0]]["data_type"][
            "value"
        ]

        # Bail if we don't have a single-entity field.
        if data_type != "entity":
            logger.warning(
                '%s\'s "%s" field should be "entity" data type, found "%s", please fix.'
                % (
                    summary_item["entity_type"],
                    args["link_fields"][summary_item["entity_type"]],
                    data_type,
                )
            )
            return

        # Get the valid entity types for the linked field.
        entity_links = link_field_schema[list(link_field_schema.keys())[0]][
            "properties"
        ]["valid_types"]["value"]

        # Bail if we have more than one valid type. Things get a bit crazy if we
        # have to check for fields on more than one entity type that may or may
        # not be used. This is a restriction folks may want to lift later. I.e.,
        # if multiple entity types are allowed, the following validators would
        # probably need to be removed. It would be more flexible, but easy to
        # make mistakes in the Django args.
        if len(entity_links) > 1:
            logger.warning(
                '%s\'s "%s" field should only accept one entity type, found %s, please fix.'
                % (
                    summary_item["entity_type"],
                    args["link_fields"][summary_item["entity_type"]],
                    entity_links,
                )
            )
            return

        # Figure out what entity type we're expecting to link to.
        found_entity_type = entity_links[0]

        # Make sure all the entity field links point to the same entity type.
        if summarize_entity_type:
            if summarize_entity_type != found_entity_type:
                logger.warning(
                    '"link_fields" setting contains entity links that reference different entity types (%s vs %s), please fix.'
                    % (summarize_entity_type, found_entity_type)
                )
                return
        else:
            summarize_entity_type = found_entity_type

        # Can check the linked entity_type field schema for field_to_update.
        if not check_entity_schema(
            sg,
            logger,
            summarize_entity_type,
            args["field_to_update"],
            ["number", "float", "currency", "text", "percent"],
        ):
            return

    return True


def check_entity_schema(sg, logger, entity_type, field_name, field_type=None):
    """
    Verifies that field_name of field_type exists in entity_type's schema.

    :param sg: An authenticated Shotgun Python API instance.
    :param logger: Logger instance.
    :param entity_type: String, a Shotgun entity type.
    :param field_name: String, the name of a field on entity_type.
    :param field_type: List of strings, the Shotgun field type field_name should be.
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
    if field_type and sg_type not in field_type:
        logger.warning(
            'SG field "%s" is type "%s" but should be of type(s) %s, please fix.'
            % (field_name, sg_type, field_type)
        )
        return

    return True


def calculate_summaries(sg, logger, event, args):
    """
    Loops over the user-specified summarize items, summarizes them and then
    combines them according to their operator types. Finally, the result is
    stored on the linked entity's field_to_update field.

    :param sg: SG API handle
    :param logger: Logger instance
    :param dict event: SG EventLogEntry
    :param dict args: Django args
    """

    # Return if we don't have all the event values we need.
    if not event.get("meta", {}).get("entity_type") or not event["meta"].get(
        "entity_id"
    ):
        logger.warning("Missing event details, skipping.")
        return

    # Make some vars for convenience.
    entity_type = event["meta"]["entity_type"]
    entity_id = event["meta"]["entity_id"]
    link_fields = args["link_fields"]

    # Re-query the entity.
    event_entity = sg.find_one(
        entity_type,
        [["id", "is", entity_id]],
        [link_fields[entity_type]],
    )

    # Bail if the entity no longer exists.
    if not event_entity:
        logger.warning(
            "%s with id %s no longer exists, skipping."
            % (
                entity_type,
                entity_id,
            )
        )
        return

    # Bail if there is no entity connected to the link_field.
    summarize_entity = event_entity[link_fields[entity_type]]
    if not summarize_entity:
        return

    # Loop over each item to summarize.
    for summary_item in args["summarize"]:

        # Grab the field values on all relevant entities.
        entities = sg.find(
            summary_item["entity_type"],
            summary_item["filters"]
            + [[link_fields[summary_item["entity_type"]], "is", summarize_entity]],
            [summary_item["field"]],
        )

        # Store the result of the summary.
        summary_item["result"] = 0.0
        for entity in entities:
            if entity[summary_item["field"]] is not None:
                if summary_item["sum_or_count"] == "count":
                    summary_item["result"] += 1
                else:
                    summary_item["result"] += entity[summary_item["field"]]

    # Calculate our final result.
    result = 0.0
    for summary_item in args["summarize"]:
        if summary_item["operator"] == "+":
            result += summary_item["result"]
        if summary_item["operator"] == "-":
            result -= summary_item["result"]
        if summary_item["operator"] == "*":
            result *= summary_item["result"]
        if summary_item["operator"] == "/":
            if summary_item["result"] == 0:
                logger.error("Cannot divide by zero, skipping.")
                return
            result /= summary_item["result"]

    # Grab the summary entity's field_to_update data type.
    summarize_entity_schema = sg.schema_field_read(summarize_entity["type"])
    field_type = (
        summarize_entity_schema.get(args["field_to_update"], {})
        .get("data_type", {})
        .get("value")
    )

    # Bail if no type comes back.
    if not field_type:
        logger.debug(
            "Could not get type for %s field %s, skipping."
            % (
                summarize_entity["type"],
                args["field_to_update"],
            )
        )
        return

    # Convert our result type to match the field type. Assume float or currency
    # (which don't need conversion) if field_type is not "number," "text," or
    # "percent".
    if field_type in ["number", "percent"]:
        result = int(result)
    elif field_type in ["text"]:
        result = str(result)

    # Update the summarize entity's field_to_update with our result.
    sg.update(
        summarize_entity["type"],
        summarize_entity["id"],
        {args["field_to_update"]: result},
    )

    # Tell the logger all about it.
    logger.info(
        "Updated %s field on %s with id %s."
        % (args["field_to_update"], summarize_entity["type"], summarize_entity["id"]),
    )
