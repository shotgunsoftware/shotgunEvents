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
    script_name = os.environ["SGDAEMON_CALCFIELD_NAME"]
    script_key = os.environ["SGDAEMON_CALCFIELD_KEY"]

    # Here's the rationale for these wacky defaults:
    # We use Project as the entity_type because it will always be there.
    # We use id for field_a because Project will always have an id field.
    # We use 1 for field_b because we don't have to worry about another
    #    float/int field existing.
    # We use the sg_description field as the field_to_update because it's
    #    unlikely that field will have been removed.
    #
    # Also, the final calculation will be:
    # field_a operator field_b = field_to_update
    # i.e., in our bogus default example:
    # project["id"] + 1 = project["sg_description"]
    # See docs/calc_field.md for more info.
    args = {
        "entity_type": "Project",
        "field_a": "id",
        "field_b": 1,
        "operator": "+",
        "field_to_update": "sg_description",
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
        {"Shotgun_%s_Change" % args["entity_type"]: [args["field_a"], args["field_b"]]},
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

    sg_num_types = ["number", "float", "currency", "percent", "text", "list"]

    args_to_check = {
        "entity_type": {"type": [str], "allow_empty": False},
        "field_a": {
            "type": [str, int, float],
            "allow_empty": False,
            "entity": args["entity_type"],
            "sg_type": sg_num_types,
        },
        "field_b": {
            "type": [str, int, float],
            "allow_empty": False,
            "entity": args["entity_type"],
            "sg_type": sg_num_types,
        },
        "field_to_update": {
            "type": [str],
            "allow_empty": False,
            "entity": args["entity_type"],
            "sg_type": sg_num_types,
        },
        "operator": {"type": [str], "allow_empty": False},
    }

    # Make sure the operator type is valid/supported.
    operator_types = ["+", "-", "*", "/"]
    if args["operator"] not in operator_types:
        logger.warning(
            'operator value is "%s", but must be of type %s, please fix.'
            % (
                args["operator"],
                operator_types,
            )
        )
        return

    # Make sure we can read the entity_type's schema.
    try:
        sg.schema_field_read(args["entity_type"])
    except Exception as e:
        logger.warning(
            'Can\'t read SG schema for "entity_type" setting\'s value ("%s"): %s'
            % (args["entity_type"], e)
        )
        return

    # Make sure at least one of the field args references a field in Shotgun.
    if type(args["field_a"]) is not str and type(args["field_b"]) is not str:
        logger.warning(
            'Both "field_a" and "field_b" are static values; at least one must reference an entity field. Please fix.'
        )
        return

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

        # We can't run any more checks unless the setting's value is non-empty.
        if args[name]:

            # If we've got an entity value, we assume the setting refers to a
            # Shotgun field. If we don't, stop the checks here.
            if "entity" not in checks:
                continue

            # If the Python arg type is int or float, we're going to use that
            # as a static value, so there is no need to check the schema.
            if type(args[name]) in [int, float]:
                continue

            # Perform some standard checks on the entity and field.
            if not check_entity_schema(
                sg, logger, checks["entity"], args[name], checks["sg_type"]
            ):
                return

    return True


def update_field_value(sg, logger, event, args):
    """
    Updates an entity's field value by calculating the result of two numbers.

    :param sg: Shotgun API handle.
    :param logger: Logger instance.
    :param event: A Shotgun EventLogEntry entity dictionary.
    :param args: Any additional misc arguments passed through this plugin.
    """

    # Return if we don't have all the field values we need.
    if not event.get("meta", {}).get("entity_id") and not event["meta"].get(
        "entity_type"
    ):
        return

    # Make some vars for convenience.
    entity_id = event["meta"]["entity_id"]
    entity_type = args["entity_type"]
    field_a_val = args["field_a"]
    field_b_val = args["field_b"]

    # Determine if we need field or static values. At least one will come back
    # as str, since we validated for that.
    fields = []
    num_1 = None
    num_2 = None
    if type(field_a_val) == str:
        fields.append(field_a_val)
    else:
        num_1 = float(field_a_val)
    if type(field_b_val) == str:
        fields.append(field_b_val)
    else:
        num_2 = float(field_b_val)

    # Re-query the entity to get updated field values.
    entity = sg.find_one(
        entity_type,
        [["id", "is", entity_id]],
        fields,
    )

    # Bail if the entity no longer exists.
    if not entity:
        logger.debug(
            "%s entity with id %s no longer exists, skipping..."
            % (
                entity_type,
                entity_id,
            )
        )
        return

    # Grab the numbers from the fields, if they exist. Use a try here because
    # string to float conversion may fail. We don't check this in the validator
    # because users can change list values at any time.
    try:
        if not num_1 and entity[field_a_val] is not None:
            num_1 = float(entity[field_a_val])
        if not num_2 and entity[field_b_val] is not None:
            num_2 = float(entity[field_b_val])
    except Exception as e:
        logger.error("Couldn't use field value, skipping: %s" % str(e))
        return

    # Assume 0 for None if only one field is empty.
    if num_1 is None:
        num_1 = float(0)
    if num_2 is None:
        num_2 = float(0)

    # Calculate our result, based on the operator type.
    op = args["operator"]
    if op == "+":
        result = num_1 + num_2
    elif op == "-":
        result = num_1 - num_2
    elif op == "*":
        result = num_1 * num_2
    elif op == "/":
        if num_2 == 0:
            logger.error(
                "Value coming from field_b is 0; cannot divide by zero, skipping."
            )
            return
        result = num_1 / num_2

    # Grab the Shotgun field data type, if the field exists.
    entity_schema = sg.schema_field_read(entity_type)
    field_type = (
        entity_schema.get(args["field_to_update"], {}).get("data_type", {}).get("value")
    )

    # Bail if no type comes back.
    if not field_type:
        logger.debug(
            "Could not get type for SG field %s, skipping." % args["field_to_update"]
        )
        return

    # Convert our data type to match the field type. Assume float or currency
    # (wich don't need conversion) if field_type is not "number," "text,"
    # "list", or "percent".
    if field_type in ["number", "percent"]:
        result = int(result)
    elif field_type in ["text", "list"]:
        result = str(result)

    # Update our entity in Shotgun. This is inside a try because the query could
    # fail with a CRUD error if a result value is not a current list option.
    try:
        sg.update(
            entity_type,
            entity_id,
            {args["field_to_update"]: result},
        )
    except Exception as e:
        logger.error("Could not update Shotgun, skipping: %s" % str(e))
        return

    # Tell the logger all about it.
    logger.info(
        "Updated %s field on %s entity (id %s) with new value: %s."
        % (
            args["field_to_update"],
            entity_type,
            entity_id,
            result,
        )
    )
