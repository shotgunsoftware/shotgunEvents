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
    script_name = os.environ["SGDAEMON_INITENTITY_NAME"]
    script_key = os.environ["SGDAEMON_INITENTITY_KEY"]

    # User-defined plugin args, change at will.
    args = {
        "entity_type": "Asset",
        "initial_data": {"description": "Brand new Asset."},
        "force": False,
        "filters": [],
    }

    # Grab an sg connection for the validator and bail if it fails.
    sg = shotgun_api3.Shotgun(server, script_name=script_name, api_key=script_key)
    if not is_valid(sg, reg.logger, args):
        reg.logger.warning("Plugin is not valid, will not register callback.")
        return

    # Register our callback with the Shotgun_%s_Change event and tell the logger
    # about it.
    reg.registerCallback(
        script_name,
        script_key,
        init_entity,
        {"Shotgun_%s_New" % args["entity_type"]: None},
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
        "entity_type": {"type": ["str"], "allow_empty": False},
        "initial_data": {"type": ["dict"], "allow_empty": False},
        "force": {"type": ["bool"], "allow_empty": False},
    }

    # Make sure we can read the entity_type's schema.
    try:
        entity_schema = sg.schema_field_read(args["entity_type"])
    except Exception as e:
        logger.warning(
            'Can\'t read SG schema for "entity_type" args\'s value ("%s"): %s'
            % (args["entity_type"], e)
        )
        return

    for name, checks in args_to_check.items():

        # Grab the arg's value type.
        value_type = type(args[name]).__name__

        # We assume unicode and str to be equivalent for these checks because
        # args come back from Django as unicode but are first set by the
        # Registrar as str.
        if value_type == "unicode":
            value_type = "str"

        # Make sure the arg value is the correct Python type.
        if checks.get("type") and value_type not in checks["type"]:
            logger.warning(
                '"%s" arg\'s value is type "%s" but should be type "%s," please fix.'
                % (name, value_type, checks["type"])
            )
            return

        # Make sure the arg has a non-empty value if allow_empty is
        # False.
        if checks.get("allow_empty") is False:
            if "bool" in checks.get("type"):
                if args[name] not in [True, False]:
                    logger.warning(
                        '"%s" arg\'s value is empty but requires a value, please fix.'
                        % (name,)
                    )
                    return
            elif not args[name]:
                logger.warning(
                    '"%s" arg\'s value is empty but requires a value, please fix.'
                    % (name,)
                )
                return

        # Now make sure each field and value referenced in initial_data
        # is valid.
        if name == "initial_data":
            # Map our SG field types to valid python object types
            valid_field_types = {
                "entity": ["dict"],
                "multi_entity": ["list"],
                "number": ["int"],
                "float": ["float"],
            }

            for field_name, field_value in args[name].items():
                field_value_type = type(field_value).__name__

                # We assume unicode and str to be equivalent for these checks because
                # args come back from Django as unicode but are first set by the
                # Registrar as str.
                if field_value_type == "unicode":
                    field_value_type = "str"

                # First, let's make sure the field is valid for our
                # entity type.
                if field_name not in entity_schema.keys():
                    logger.warning(
                        '%s entity field "%s" does not exist in Shotgun, please fix.'
                        % (
                            args["entity_type"],
                            field_name,
                        )
                    )
                    return

                # Since we've already verified that the field exists
                # for the entity type, just grab the Shotgun field data
                # type to do additional validation.
                sg_type = entity_schema[field_name]["data_type"]["value"]

                # If there isn't a mapping from the SG field type to a
                # python object type defined above, assume that the
                # field will accept a string value
                valid_value_types = valid_field_types.get(sg_type, ["str"])

                # make sure the initial value provided will work for this field
                if field_value_type not in valid_value_types:
                    logger.warning(
                        'Initial value for SG field "%s" is type "%s" but should be of type(s) "%s," please fix.'
                        % (
                            field_name,
                            field_value_type,
                            valid_value_types,
                        )
                    )
                    return
                # if we have a list field, make sure the initial value is valid
                if sg_type in ["list", "status_list"]:
                    valid_values = (
                        entity_schema[field_name]
                        .get("properties", {})
                        .get("valid_values", {})
                        .get("value")
                    )
                    if valid_values and field_value not in valid_values:
                        logger.warning(
                            'Initial value for SG field "%s" is "%s" but must be one of the following: "%s".'
                            % (
                                field_name,
                                str(field_value),
                                ", ".join(valid_values),
                            )
                        )
                        return

    return True


def init_entity(sg, logger, event, args):
    """
    Updates an entity with some initial values on creation.

    :param sg: Shotgun API handle.
    :param logger: Logger instance.
    :param event: A Shotgun EventLogEntry entity dictionary.
    :param args: Any additional misc arguments passed through this plugin.
    """

    # Return if we don't have all the field values we need; we're intentionally
    # excluding event["meta"]["new_value"] because None is a valid value.
    if not event.get("meta", {}).get("entity_id"):
        return

    # Make some vars for convenience.
    entity_id = event["meta"]["entity_id"]
    entity_type = args["entity_type"]

    # Re-query the entity so we don't clobber a value that may have
    # been populated by a user
    fields_to_update = list(args["initial_data"].keys())
    entity = sg.find_one(
        entity_type,
        args["filters"] + [["id", "is", entity_id]],
        fields_to_update,
    )

    # Bail if we don't have an entity. This would happen if user-specified
    # filters don't match the event entity. This is a "feature," so folks can
    # target entities w/certain field values. E.g., the trigger could only init
    # values on an Asset entity with its sg_asset_type field value set to
    # "character".
    if not entity:
        return

    # Are we supposed to clobber existing values?
    force_update = args["force"]

    update_data = {}
    # Convert anything that's currently unicode to a string.
    for key, value in args["initial_data"].items():
        key = str(key)
        value = str(value)

        # If the field is already populated, don't clobber it unless
        # we've been told to.
        if entity[key]:
            if force_update:
                update_data[key] = value
        else:
            update_data[key] = value

    if update_data:
        sg.update(entity_type, entity_id, update_data)

        # Tell the logger what happened.
        logger.info(
            "%s with id %s updated with new data: %s"
            % (entity_type, entity_id, update_data)
        )
