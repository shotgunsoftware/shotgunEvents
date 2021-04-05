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
    script_name = os.environ["SGDAEMON_UVCV_NAME"]
    script_key = os.environ["SGDAEMON_UVCV_KEY"]

    args = {
        "first_frame_field": "sg_first_frame",
        "last_frame_field": "sg_last_frame",
        "cut_in_field": "sg_cut_in",
        "cut_out_field": "sg_cut_out",
        "cut_length_field": "sg_cut_length",
        "head_duration_field": "sg_head_duration",
        "tail_duration_field": "sg_tail_duration",
        "frame_count_field": "frame_count",
        "default_head_in": 0,
        "default_tail_out": 0,
    }

    args["trigger_fields"] = [
        args["first_frame_field"],
        args["cut_in_field"],
        args["cut_out_field"],
        args["head_duration_field"],
        args["tail_duration_field"],
    ]

    # Grab an sg connection for the validator.
    sg = shotgun_api3.Shotgun(server, script_name=script_name, api_key=script_key)

    # Bail if our validator fails.
    if not is_valid(sg, reg.logger, args):
        reg.logger.warning("Plugin is not valid, will not register callback.")
        return

    reg.registerCallback(
        script_name,
        script_key,
        update_version_cut_values,
        {"Shotgun_Version_Change": args["trigger_fields"]},
        args,
    )
    reg.logger.debug("Registered callback.")


def check_entity_schema(sg, logger, entity_type, field_name, field_type):
    """
    Verifies that field_name of field_type exists in entity_type's schema.

    :param sg: An authenticated Shotgun Python API instance.
    :param entity_type: String, a Shotgun entity type.
    :param field_name: String, the name of a field on entity_type.
    :param field_type: List of strings, the Shotgun field type field_name should be.
    :returns: True if valid, None otherwise.
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
            % (entity_type, field_name,)
        )
        return

    # Make sure the field is the correct Shotgun type.
    if sg_type not in field_type:
        logger.warning(
            'SG field "%s" is type "%s" but should be of type(s) "%s," please fix.'
            % (field_name, sg_type, field_type)
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

    args_to_check = {
        "first_frame_field": {
            "type": [str],
            "allow_empty": False,
            "entity": "Version",
            "sg_type": "number",
        },
        "last_frame_field": {
            "type": [str],
            "allow_empty": False,
            "entity": "Version",
            "sg_type": "number",
        },
        "cut_in_field": {
            "type": [str],
            "allow_empty": False,
            "entity": "Version",
            "sg_type": "number",
        },
        "cut_out_field": {
            "type": [str],
            "allow_empty": False,
            "entity": "Version",
            "sg_type": "number",
        },
        "cut_length_field": {
            "type": [str],
            "allow_empty": False,
            "entity": "Version",
            "sg_type": "number",
        },
        "head_duration_field": {
            "type": [str],
            "allow_empty": False,
            "entity": "Version",
            "sg_type": "number",
        },
        "tail_duration_field": {
            "type": [str],
            "allow_empty": False,
            "entity": "Version",
            "sg_type": "number",
        },
        "frame_count_field": {
            "type": [str],
            "allow_empty": False,
            "entity": "Version",
            "sg_type": "number",
        },
        "default_head_in": {"type": [int], "allow_empty": False,},
        "default_tail_out": {"type": [int], "allow_empty": False,},
    }

    for name, checks in args_to_check.items():

        # Grab the setting's value type.
        value_type = type(args[name])

        # Make sure the setting value is the correct Python type.
        if value_type not in checks["type"]:
            logger.warning(
                '"%s" setting\'s value is type "%s" but should be type "%s," please fix.'
                % (name, value_type, checks["type"])
            )
            return

        # Make sure the setting has a non-empty value if allow_empty is False.
        if checks.get("allow_empty") is False and args[name] is None:
            logger.warning(
                '"%s" setting\'s value is empty but requires a value, please fix.'
                % (name,)
            )
            return

        # We can't run any more checks unless the setting's value is non-empty.
        if args[name]:

            # If we've got an entity value, we assume the setting refers to a
            # Shotgun field. If we don't, stop the checks here.
            if "entity" not in checks:
                continue

            # Perform some standard checks on the entity and field.
            if not check_entity_schema(
                sg, logger, checks["entity"], args[name], checks["sg_type"]
            ):
                return

    return True


def update_version_cut_values(sg, logger, event, args):
    """
    PART 1 - When a Version's first frame value is updated, do the following math:

    Last Frame = First Frame + Frame Count - 1
    Cut In = First Frame + Head Duration
    Cut Out = First Frame + Head Duration + Cut Length - 1

    PART 2 - When a Version's cut in or cut out value is updated, do the following math:

    Cut Length = Cut Out - Cut In + 1
    Head Duration = Cut In - First Frame
    Tail Duration = Last Frame - Cut Out

    PART 3 - When a Version's head duration or tail duration is updated, do the following math:

    First Frame = Cut In - Head Duration
    Last Frame = Cut Out + Tail Duration
    Frame Count = Head Duration + Cut Length + Tail Duration

    :param sg: Shotgun API handle.
    :param logger: Logger instance.
    :param event: A Shotgun EventLogEntry entity dictionary.
    :param args: Any additional misc arguments passed through this plugin.
    """

    # Return if we don't have all the field values we need.
    if not event.get("meta", {}).get("entity_id"):
        return

    # Make some vars for convenience.
    entity_id = event["meta"]["entity_id"]

    # Requery the Version to gather additional field values.
    version = sg.find_one(
        "Version",
        [["id", "is", entity_id]],
        [
            "code",
            args["frame_count_field"],
            args["cut_length_field"],
            args["last_frame_field"],
        ]
        + args["trigger_fields"],
    )

    # Return if the Version isn't found.
    if not version:
        logger.debug("No Version with id %s.", entity_id)
        return

    # Initialize our update_data dict.
    update_data = {}

    # Note: if head or tail values are empty we use the values in the default
    # head and tail args. For all other missing values, we need to skip the calculation.

    # Part 1
    if event["attribute_name"] == args["first_frame_field"]:
        required_fields = [
            version[args["first_frame_field"]],
            version[args["frame_count_field"]],
            version[args["cut_length_field"]],
        ]
        if field_values_valid(required_fields):
            update_data[args["last_frame_field"]] = (
                version[args["first_frame_field"]]
                + version[args["frame_count_field"]]
                - 1
            )
            update_data[args["cut_in_field"]] = version[args["first_frame_field"]] + (
                version[args["head_duration_field"]] or args["default_head_in"]
            )
            update_data[args["cut_out_field"]] = (
                update_data[args["cut_in_field"]]
                + version[args["cut_length_field"]]
                - 1
            )

    # Part 2
    elif event["attribute_name"] in [args["cut_in_field"], args["cut_out_field"]]:
        required_fields = [
            version[args["cut_out_field"]],
            version[args["cut_in_field"]],
            version[args["first_frame_field"]],
            version[args["last_frame_field"]],
        ]
        if field_values_valid(required_fields):
            update_data[args["cut_length_field"]] = (
                version[args["cut_out_field"]] - version[args["cut_in_field"]] + 1
            )
            update_data[args["head_duration_field"]] = (
                version[args["cut_in_field"]] - version[args["first_frame_field"]]
            )
            update_data[args["tail_duration_field"]] = (
                version[args["last_frame_field"]] - version[args["cut_out_field"]]
            )

    # Part 3
    else:
        required_fields = [
            version[args["cut_in_field"]],
            version[args["cut_out_field"]],
            version[args["cut_length_field"]],
        ]
        if field_values_valid(required_fields):
            update_data[args["first_frame_field"]] = version[args["cut_in_field"]] - (
                version[args["head_duration_field"]] or args["default_head_in"]
            )
            update_data[args["last_frame_field"]] = version[args["cut_out_field"]] + (
                version[args["tail_duration_field"]] or args["default_tail_out"]
            )
            update_data[args["frame_count_field"]] = (
                (version[args["head_duration_field"]] or args["default_head_in"])
                + version[args["cut_length_field"]]
                + (version[args["tail_duration_field"]] or args["default_tail_out"])
            )

    if update_data:
        logger.info("Updating Version %d:" % entity_id)
        sg.update("Version", entity_id, update_data)


def field_values_valid(field_values):
    """
    Loop over a list of values and make sure they aren't empty. If all values
    are legit, return True, otherwise False.

    :param field_values: A list of field values to validate.
    :returns: False if any field values are None or "", True otherwise.
    """

    for field_value in field_values:
        if not field_value:
            return False

    return True
