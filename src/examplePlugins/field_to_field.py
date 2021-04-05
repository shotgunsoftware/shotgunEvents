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

    # User-defined plugin args, change at will.
    args = {
        "entity_type": "Task",
        "from_field": "sg_status_list",
        "from_value": "na",
        "to_field": "duration",
        "to_value": 0,
    }

    # Grab an sg connection for the validator.
    sg = shotgun_api3.Shotgun(server, script_name=script_name, api_key=script_key)

    # Bail if our validator fails.
    if not is_valid(sg, reg.logger, args):
        reg.logger.warning("Plugin is not valid, will not register callback.")
        return

    # Register our callback with the Shotgun_%s_Change event and tell the logger
    # about it.
    reg.registerCallback(
        script_name,
        script_key,
        update_field_value,
        {"Shotgun_%s_Change" % args["entity_type"]: args["from_field"]},
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

    args_to_check = {
        "entity_type": {"type": [str], "allow_empty": False},
        "from_field": {"type": [str], "allow_empty": False},
        "from_value": {"allow_empty": True},
        "to_field": {"type": [str], "allow_empty": False},
        "to_value": {"allow_empty": True},
    }

    for name, checks in args_to_check.items():

        # Bail if we're missing any required args.
        try:
            args[name]
        except Exception as e:
            logger.warning("Missing arg: %s." % name)
            return

        # Make sure the arg value is the correct Python type.
        value_type = type(args[name])
        if checks.get("type") and value_type not in checks["type"]:
            logger.warning(
                "%s arg's value is type %s but should be type %s, please fix."
                % (name, value_type, checks["type"])
            )
            return

        # Make sure the arg has a non-empty value if allow_empty is False.
        if checks.get("allow_empty") is False and not args[name]:
            logger.warning(
                "%s arg's value is empty but requires a value, please fix." % (name,)
            )
            return

    # Make sure we can read the entity_type's schema.
    try:
        entity_schema = sg.schema_field_read(args["entity_type"])
    except Exception as e:
        logger.warning(
            'Can\'t read SG schema for "entity_type" args\'s value ("%s"): %s'
            % (args["entity_type"], e)
        )
        return

    # Make sure from_field and to_field are in the entity type's schema.
    for field in [args["from_field"], args["to_field"]]:
        if field not in entity_schema:
            logger.warning("%s not in entity schema, please fix." % field)
            return

    return True


def update_field_value(sg, logger, event, args):
    """
    Updates an entity's field value if the conditions are met.

    :param sg: Shotgun API handle.
    :param logger: Logger instance.
    :param event: A Shotgun EventLogEntry entity dictionary.
    :param args: Any additional misc arguments passed through this plugin.
    """

    # Return if we don't have all the field values we need; we're intentionally
    # excluding event["meta"]["new_value"] because None is a valid value.
    if not event.get("meta", {}).get("entity_id"):
        logger.debug("event['meta']['entity_id'] missing, skipping event.")
        return

    # Make some vars for convenience.
    entity_id = event["meta"]["entity_id"]
    entity_type = args["entity_type"]

    # If our entity's from_field is set to from_value, the to_field for that
    # same entity should be updated to to_value.
    if event["meta"]["new_value"] == args["from_value"]:
        try:
            sg.update(
                entity_type, entity_id, {args["to_field"]: args["to_value"]},
            )

            # Tell the logger about it.
            logger.info(
                "Updated %s with id %s with new %s value %s."
                % (entity_type, entity_id, args["to_field"], args["to_value"],)
            )
        except Exception as e:
            logger.error(
                "Could not update %s with id %s: %s"
                % (args["entity_type"], entity_id, e)
            )
