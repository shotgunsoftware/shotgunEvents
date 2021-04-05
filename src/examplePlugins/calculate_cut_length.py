# Copyright 2018 Autodesk, Inc.  All rights reserved.
#
# Use of this software is subject to the terms of the Autodesk license agreement
# provided at the time of installation or download, or which otherwise accompanies
# this software in either electronic or hard copy form.
#

# See docs folder for detailed usage info.

import os
import math
import shotgun_api3


def registerCallbacks(reg):
    """
    Register our callbacks.

    :param reg: A Registrar instance provided by the event loop handler.
    """

    # Grab authentication env vars for this plugin. Install these into the env
    # if they don't already exist.
    server = os.environ["SG_SERVER"]
    script_name = os.environ["SGDAEMON_CALCULATECUTLENGTH_NAME"]
    script_key = os.environ["SGDAEMON_CALCULATECUTLENGTH_KEY"]

    # User-defined plugin args, change at will.
    args = {
        "entity_type": "Shot",
        "cut_in_field": "sg_cut_in",
        "cut_out_field": "sg_cut_out",
        "cut_duration_field": "sg_cut_duration",
        "cut_length_rt_field": "sg_cut_length_r_t",
        "fps": 24.0,
    }

    # Grab an sg connection for the validator.
    sg = shotgun_api3.Shotgun(server, script_name=script_name, api_key=script_key)

    # Bail if our validator fails.
    if not is_valid(sg, reg.logger, args):
        reg.logger.warning("Plugin is not valid, will not register callback.")
        return

    event_filter = {
        "Shotgun_%s_Change"
        % args["entity_type"]: [
            args["cut_in_field"],
            args["cut_out_field"],
            args["cut_duration_field"],
        ]
    }

    reg.registerCallback(
        script_name, script_key, update_cut_duration_timecode, event_filter, args,
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

    args_to_check = {
        "fps": {"type": ["float"]},
        "cut_in_field": {"sg_type": ["number"], "type": ["str"]},
        "cut_out_field": {"sg_type": ["number"], "type": ["str"]},
        "cut_duration_field": {"sg_type": ["number"], "type": ["str"]},
        "cut_length_rt_field": {"sg_type": ["timecode"], "type": ["str"]},
    }

    # Make sure we can read the entity_type's schema.
    try:
        entity_schema = sg.schema_field_read(args["entity_type"])
    except Exception as e:
        logger.warning(
            'Can\'t read SG schema for "entity_type" setting\'s value ("%s"): %s'
            % (args["entity_type"], e)
        )
        return

    for name, type_targets in args_to_check.items():

        # Grab the setting's value type.
        value_type = type(args[name]).__name__

        # We assume unicode and str to be equivalent for these checks because
        # args come back from Django as unicode but are first set by the
        # Registrar as str.
        if value_type == "unicode":
            value_type = "str"

        # Make sure the setting value is the correct Python type.
        if value_type not in type_targets["type"]:
            logger.warning(
                '"%s" setting\'s value is type "%s" but should be type "%s," please fix.'
                % (name, value_type, type_targets["type"])
            )
            return

        # If we've got a sg_type, we assume the setting refers to a Shotgun
        # field. If we don't, stop the checks here.
        if not type_targets.get("sg_type"):
            continue

        # Grab the Shotgun field data type, if the field exists.
        sg_type = entity_schema.get(args[name], {}).get("data_type", {}).get("value")

        # Make sure the field exists on the entity.
        if not sg_type:
            logger.warning(
                '"%s" setting refers to a %s entity field ("%s") that doesn\'t exist, please fix.'
                % (name, args["entity_type"], args[name],)
            )
            return

        # Make sure the field is the correct Shotgun type.
        if sg_type not in type_targets["sg_type"]:
            logger.warning(
                '"%s" setting refers to a SG field that is type "%s" but should be type "%s," please fix.'
                % (name, sg_type, type_targets["sg_type"])
            )
            return

    return True


def update_cut_duration_timecode(sg, logger, event, args):
    """
    Desired logic:

    Part 1 - Updates to Cut In and Cut Out

    When the Cut In or Cut Out values are updated, calculate the following fields:
`
         Cut Length = Cut Out - Cut In + 1
         Cut Length R/T = Cut Length in timecode

    Part 2 - Updates to Cut Length

    When the Cut Length value is updated by hand, calculate the following field:
`
         Cut Length R/T = Cut Length in timecode

    :param sg: Shotgun API handle.
    :param logger: Logger instance.
    :param event: A Shotgun EventLogEntry entity dictionary.
    :param args: Any additional misc arguments passed through this plugin.
    """

    # Return if we don't have all the field values we need.
    if not event.get("attribute_name") or not event.get("meta", {}).get("entity_id"):
        return

    # Make some vars for convenience.
    entity_id = event["meta"]["entity_id"]
    attribute_name = event["attribute_name"]

    # Re-query the entity to gather extra field values.
    entity = sg.find_one(
        args["entity_type"],
        [["id", "is", entity_id]],
        [args["cut_in_field"], args["cut_out_field"], args["cut_duration_field"]],
    )

    # Return if no entity was found.
    if not entity:
        logger.info(
            "Couldn't retrieve %s with id %d" % (args["entity_type"], entity_id)
        )
        return

    # Init our entity_type update dict.
    new_data = {}

    # If the cut in or cut out values were changed...
    if attribute_name in [args["cut_in_field"], args["cut_out_field"]]:

        # ...return if either the cut in or cut out values are not set...
        if not entity[args["cut_in_field"]] or not entity[args["cut_out_field"]]:
            logger.debug("Either cut in or cut out value is missing, skipping.")
            return

        # ... or enter updated values into new_data for the cut_duration_field
        # and cut_length_rt_field. Round up anything in cut_length_rt_field that
        # isn't an int.
        new_data[args["cut_duration_field"]] = (
            entity[args["cut_out_field"]] - entity[args["cut_in_field"]] + 1
        )
        new_data[args["cut_length_rt_field"]] = int(
            math.ceil(new_data[args["cut_duration_field"]] / args["fps"] * 1000)
        )

    # Otherwise...
    else:

        # ...return if the cut duration field is empty...
        if not entity[args["cut_duration_field"]]:
            logger.debug("No cut length value, skipping.")
            return

        # ...or enter an updated value into new_data for the cut_length_rt_field field.
        new_data[args["cut_length_rt_field"]] = int(
            math.ceil(entity[args["cut_duration_field"]] / args["fps"] * 1000)
        )

    # If we have something to do, do it!
    if new_data:

        sg.update(args["entity_type"], entity["id"], new_data)

        logger.info(
            "Updated %s (ID %s) with %s"
            % (args["entity_type"], str(entity["id"]), str(new_data))
        )

    # Otherwise tell the logger to bugger off.
    else:
        logger.info(
            "Did not update %s with ID %s, nothing to do."
            % (args["entity_type"], entity["id"])
        )
