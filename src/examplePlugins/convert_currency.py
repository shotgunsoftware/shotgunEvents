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
    script_name = os.environ["SGDAEMON_CONVERTCURRENCY_NAME"]
    script_key = os.environ["SGDAEMON_CONVERTCURRENCY_KEY"]

    # User-defined plugin args, change at will.
    args = {
        "entity_type": "CustomEntity02",
        "from_currency_field": "sg_base_amount",
        "to_currency_field": "sg_amount",
        "exchange_rate_field": "sg_exchange_rate",
        "status_field": "sg_status_list",
        "ignore_statuses": ["na"],
    }

    # Grab an sg connection for the validator.
    sg = shotgun_api3.Shotgun(server, script_name=script_name, api_key=script_key)

    # Bail if our validator fails.
    if not is_valid(sg, reg.logger, args):
        reg.logger.warning("Plugin is not valid, will not register callback.")
        return

    # Build our event filter.
    event_filter = {
        "Shotgun_%s_Change"
        % args["entity_type"]: [
            args["from_currency_field"],
            args["exchange_rate_field"],
            args["status_field"],
        ],
    }

    # Register our callback with the Shotgun_%s_Change event and tell the logger
    # about it.
    reg.registerCallback(
        script_name, script_key, convert_currency, event_filter, args,
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

    # Define what types are valid for Shotgun fields and args values.
    args_to_check = {
        "from_currency_field": {"sg_type": ["float", "currency"], "type": [str]},
        "to_currency_field": {"sg_type": ["float", "currency"], "type": [str]},
        "exchange_rate_field": {"sg_type": ["list"], "type": [str]},
        "status_field": {"sg_type": ["status_list", "list"], "type": [str]},
        "ignore_statuses": {"type": [list]},
    }

    # Make sure we can read the entity_type's schema.
    try:
        entity_schema = sg.schema_field_read(args["entity_type"])
    except Exception as e:
        raise ValueError(
            'Can\'t read SG schema for "entity_type" setting\'s value ("%s"): %s'
            % (args["entity_type"], e)
        )

    for name, type_target in args_to_check.items():

        # Grab the setting's value type.
        value_type = type(args[name])

        # Make sure the setting value is the correct Python type.
        if value_type not in type_target["type"]:
            raise ValueError(
                '"%s" setting\'s value is type "%s" but should be of type(s) %s, please fix.'
                % (name, value_type, type_target["type"])
            )

        # If we've got a sg_type, we assume the setting refers to a Shotgun
        # field. If we don't, stop the checks here.
        if not type_target.get("sg_type"):
            continue

        # Grab the Shotgun field data type, if the field exists.
        sg_type = entity_schema.get(args[name], {}).get("data_type", {}).get("value")

        # Make sure the field exists on the entity.
        if not sg_type:
            raise ValueError(
                '"%s" setting refers to a %s entity field ("%s") that doesn\'t exist, please fix.'
                % (name, args["entity_type"], args[name],)
            )

        # Make sure the field is the correct Shotgun type.
        if sg_type not in type_target["sg_type"]:
            raise ValueError(
                '"%s" setting refers to a SG field that is type "%s" but should be of type(s) %s, please fix.'
                % (name, sg_type, type_target["sg_type"])
            )

    return True


def convert_currency(sg, logger, event, args):
    """
    Converts currency via an exchange rate on a given entity.

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

    # Re-query the entity to gather additional field data.
    cost = sg.find_one(
        args["entity_type"],
        [["id", "is", entity_id]],
        [
            args["from_currency_field"],
            args["exchange_rate_field"],
            args["status_field"],
        ],
    )

    # Return if we don't have a cost entity.
    if not cost:
        logger.debug("No %s found (cost entity), skipping." % args["entity_type"])
        return

    # Return if we don't have from-currency or exchange rate values.
    if not cost[args["from_currency_field"]] or not cost[args["exchange_rate_field"]]:
        logger.debug(
            "Missing %s or %s value, skipping."
            % (args["from_currency_field"], args["exchange_rate_field"],)
        )
        return

    # Return if the status is in the ignore_statuses list.
    if cost[args["status_field"]] in args["ignore_statuses"]:
        logger.debug(
            '"%s" status is in %s, skipping.'
            % (cost[args["status_field"]], args["ignore_statuses"])
        )
        return

    # Return if the plugin was triggered by the status field and the old value
    # is not in the ignore_statuses list. We only need this trigger to execute
    # if it's flushing out blank costs after coming back from an excluded status.
    if (
        event["attribute_name"] == args["status_field"]
        and event["meta"]["old_value"] not in args["ignore_statuses"]
    ):
        logger.debug(
            "Cost status was not previously of type(s) %s, skipping."
            % args["ignore_statuses"]
        )
        return

    # Do the currency conversion.
    converted_amount = cost[args["from_currency_field"]] * float(
        cost[args["exchange_rate_field"]]
    )

    # Update the entity record.
    cost = sg.update(
        args["entity_type"], cost["id"], {args["to_currency_field"]: converted_amount}
    )

    # Tell the logger about it.
    logger.debug("Updated %s with ID %s: %s" % (args["entity_type"], entity_id, cost,))
