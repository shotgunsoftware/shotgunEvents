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
    script_name = os.environ["SGDAEMON_FIELDTOFIELD_NAME"]
    script_key = os.environ["SGDAEMON_FIELDTOFIELD_KEY"]

    args = {
        "entity_type": "Version",
        "entity_name_field": "code",
        "head_duration_field": "sg_head_duration",
        "tail_duration_field": "sg_tail_duration",
        "timecode_cut_in_field": "sg_timecode_cut_in",
        "timecode_cut_out_field": "sg_timecode_cut_out",
        "timecode_in_field": "sg_timecode_in",
        "timecode_out_field": "sg_timecode_out",
        "first_frame_field": "sg_first_frame",
        "last_frame_field": "sg_last_frame",
        "frame_count_field": "frame_count",
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
            args["head_duration_field"],
            args["tail_duration_field"],
            args["first_frame_field"],
        ]
    }

    reg.registerCallback(
        script_name,
        script_key,
        update_timecode_and_frame_values,
        event_filter,
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
        "entity_type": {"type": [str], "allow_empty": False},
        "entity_name_field": {
            "type": [str],
            "allow_empty": False,
            "entity": args["entity_type"],
            "sg_type": "text",
        },
        "head_duration_field": {
            "type": [str],
            "allow_empty": False,
            "entity": args["entity_type"],
            "sg_type": "number",
        },
        "tail_duration_field": {
            "type": [str],
            "allow_empty": False,
            "entity": args["entity_type"],
            "sg_type": "number",
        },
        "timecode_cut_in_field": {
            "type": [str],
            "allow_empty": False,
            "entity": args["entity_type"],
            "sg_type": "text",
        },
        "timecode_cut_out_field": {
            "type": [str],
            "allow_empty": False,
            "entity": args["entity_type"],
            "sg_type": "text",
        },
        "timecode_in_field": {
            "type": [str],
            "allow_empty": False,
            "entity": args["entity_type"],
            "sg_type": "text",
        },
        "timecode_out_field": {
            "type": [str],
            "allow_empty": False,
            "entity": args["entity_type"],
            "sg_type": "text",
        },
        "first_frame_field": {
            "type": [str],
            "allow_empty": False,
            "entity": args["entity_type"],
            "sg_type": "number",
        },
        "last_frame_field": {
            "type": [str],
            "allow_empty": False,
            "entity": args["entity_type"],
            "sg_type": "number",
        },
        "frame_count_field": {
            "type": [str],
            "allow_empty": False,
            "entity": args["entity_type"],
            "sg_type": "number",
        },
        "fps": {"type": [float]},
    }

    # Make sure we can read the entity_type's schema.
    try:
        sg.schema_field_read(args["entity_type"])
    except Exception as e:
        logger.warning(
            'Can\'t read SG schema for "entity_type" setting\'s value ("%s"): %s'
            % (args["entity_type"], e)
        )
        return

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
        if checks.get("allow_empty") is False and not args[name]:
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


def get_updates(sg, logger, event, args, entity):
    """
    Updates timecode, handles, and other editorial field values.

    :param sg: Shotgun API handle.
    :param logger: Logger instance.
    :param event: A Shotgun EventLogEntry entity dictionary.
    :param args: Any additional misc arguments passed through this plugin.
    :param entity: A Shotgun entity dict.
    :return: A dictionary with entity values to update, or None.
    """

    # Initialize our update_data dict.
    update_data = {}

    # If the head duration changes, update the timecode cut in value.
    if event["attribute_name"] == args["head_duration_field"]:

        # Return if there's no value in the timecode cut in field.
        if not entity[args["timecode_cut_in_field"]]:
            return

        # Retrieve the first frame from timecode.
        first_frame = frame_from_timecode(
            entity[args["timecode_cut_in_field"]], args["fps"]
        ) - (entity[args["head_duration_field"]] or 0)

        # Register our first_frame value in the update dict.
        update_data[args["timecode_in_field"]] = timecode_from_frame(
            first_frame, args["fps"]
        )

    # If the tail duration changes, update the timecode out value.
    elif event["attribute_name"] == args["tail_duration_field"]:

        # Return if there's no value in the timecode cut out field.
        if not entity[args["timecode_cut_out_field"]]:
            return

        # Retrieve a frame to convert from timecode.
        timecode_frame = frame_from_timecode(
            entity.get(args["timecode_cut_out_field"]), args["fps"]
        ) + (entity.get(args["tail_duration_field"]) or 0)

        # Register our timecode_frame value in the update dict.
        update_data[args["timecode_out_field"]] = timecode_from_frame(
            timecode_frame, args["fps"]
        )

    # If the first frame changes, adjust the last frame value.
    elif event["attribute_name"] == args["first_frame_field"]:

        # Return if there's no value in the first frame field.
        if not entity[args["first_frame_field"]]:
            return

        # Register our last_frame value in the update dict.
        update_data[args["last_frame_field"]] = (
            entity[args["first_frame_field"]] or 0
        ) + (entity[args["frame_count_field"]] or 0)

    # If the update_data dict is not empty, we have to also recompute and update
    # the frame_count and last_frame values.
    if update_data:

        timecode_out = (
            update_data[args["timecode_out_field"]]
            if args["timecode_out_field"] in update_data
            else entity[args["timecode_out_field"]]
        )

        timecode_in = (
            update_data[args["timecode_in_field"]]
            if args["timecode_in_field"] in update_data
            else entity[args["timecode_in_field"]]
        )

        frame_duration = frame_from_timecode(
            timecode_out, args["fps"]
        ) - frame_from_timecode(timecode_in)
        update_data[args["frame_count_field"]] = frame_duration

        if entity[args["first_frame_field"]]:
            update_data[args["last_frame_field"]] = (
                entity[args["first_frame_field"]] or 0
            ) + (update_data[args["frame_count_field"]] or 0)

    return update_data


def frame_from_timecode(timecode, fps=24.0):
    """
    Return the frame corresponding to the given timecode, for the given fps.

    :param timecode: String, timecode.
    :param fps: Float representing frames-per-second.
    :returns: Int representing a number of frames.
    """

    # Return a frame of 0 if we don't have a valid timecode or we have a drop
    # frame timecode (drop frame is unsupported).
    if not timecode or ":" not in timecode or ";" in timecode:
        return 0

    (hour, minute, second, frame) = timecode.split(":")
    hours = int(hour)
    minutes = int(minute)
    seconds = int(second)
    frames = int(frame)

    seconds = (hours * 60 * 60) + (minutes * 60) + seconds
    frames = (seconds * fps) + frames

    return int(round(frames))


def timecode_from_frame(frame_duration, fps=24.0):
    """
    Return the timecode corresponding to the given frame, for the given fps.

    :param frame_duration: Int representing a number of frames.
    :param fps: Float value representing frames per second.
    :returns: String representing a non-drop-frame timecode value.
    """

    # Total number of seconds in whole clip.
    seconds = frame_duration / fps

    # Remainder frames from seconds calculation.
    remainder = seconds - int(seconds)
    frames = int(round(remainder * fps))

    # Total number of minutes in the whole clip.
    minutes = int(seconds) / 60

    # Remainder seconds from minutes calculation
    remainder = minutes - int(minutes)
    seconds = int(round(remainder * 60))

    # Total number of hours in the whole clip.
    hours = int(minutes) / 60

    # Remainder minutes from hours calculation.
    remainder = hours - int(hours)
    minutes = int(round(remainder * 60))

    # Hours without the remainder.
    hours = int(hours)

    timecode = "%02d:%02d:%02d:%02d" % (hours, minutes, seconds, frames)

    return timecode


def update_timecode_and_frame_values(sg, logger, event, args):
    """
    Update both timecode and frame values.

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
    entity_type = args["entity_type"]

    # Requery the entity to gather additional field values.
    entity = sg.find_one(
        entity_type,
        [["id", "is", entity_id]],
        [
            args["entity_name_field"],
            args["timecode_in_field"],
            args["timecode_cut_in_field"],
            args["head_duration_field"],
            args["timecode_out_field"],
            args["timecode_cut_out_field"],
            args["tail_duration_field"],
            args["first_frame_field"],
            args["frame_count_field"],
        ],
    )

    # Return if the entity isn't found.
    if not entity:
        logger.debug("No %s with id %s.", (entity_type, entity_id))
        return

    # Determine and calculate values to update on the entity, if any.
    update_data = get_updates(sg, logger, event, args, entity)

    # Update our entity with the values in update_data.
    if update_data:
        sg.update(entity_type, entity_id, update_data)
        logger.info(
            "%s %s updated with %s."
            % (
                entity_type,
                entity[args["entity_name_field"]],
                update_data,
            )
        )
    else:
        logger.info(
            "Nothing to update on %s %s with id %s."
            % (
                entity_type,
                entity[args["entity_name_field"]],
                entity_id,
            )
        )
