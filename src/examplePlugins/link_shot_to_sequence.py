# Copyright 2018 Autodesk, Inc.  All rights reserved.
#
# Use of this software is subject to the terms of the Autodesk license agreement
# provided at the time of installation or download, or which otherwise accompanies
# this software in either electronic or hard copy form.
#

# See docs folder for detailed usage info.

"""
Required fields
    Shot entity:
         - Shot Code {code}
         - Sequence {sg_sequence}
    Sequence entity:
        - Sequence Code {code}

Logic
    When a Shot is created either by Human User or by Script User, and the Sequence field is
    blank, update the Sequence based on the following criteria:

    1. The Shot Code matches the proper Shot naming convention defined by the "shot_code_regex"
       plugin setting.

    2. There's a Sequence where the "Sequence Code" field (defined by the "sequence_code_field"
       plugin setting) matches the first grouping match of the "shot_code_regex"

    3. The Sequence matches any additional filters defined in the "sequence_filters" plugin
       setting.

    If a valid matching Sequence is found, update the Shot's Sequence field accordingly.


Plugin Args
    - shot_code_regex: (required) String containing the regex used to match a valid Shot code
                       as well as capture a valid Sequence code. The captured Sequence code
                       must be in the first group.
    - sequence_code_regex_group: In the case there are multiple groups identified in the
                                 shot_code_regex, the group number that identifies the Sequence
                                 code to lookup.
                                 (default = 1)
    - sequence_code_field: String designating the field name to search for the
                           sequence code captured by the shot_code_regex.
                           (default = sg_sequence_code)
    - sequence_filters: List of additional filters to use when finding a matching Sequence.
                        The default will always filter for Sequences in the current Project
                        and Sequences where the "sequence_code_field" matches the grouping
                        match from the shot_code_regex.
                        (default = [])

    Example:
        This will match a Shot named JL4001 and capture "JL" as the Sequence code and will query
        SG for a Sequence in the current Project where sg_sequence_code = "JL" and
        sg_status_list != "na":

        {
            "shot_code_regex": "^([A-Za-z]{2})([0-9]{4})\",
            "sequence_code_field": "sg_sequence_code",
            "sequence_filters": [["sg_status_list", "is_not", "na"]]
        }
"""

import re
import os
import shotgun_api3


def registerCallbacks(reg):
    """
    Register our callbacks
    :param reg: A Registrar instance provided by the event loop handler
    """

    # Grab authentication env vars for this plugin. Install these into the env
    # if they don't already exist.
    server = os.environ["SG_SERVER"]
    script_name = os.environ["SGDAEMON_LINKSHOTTOSEQUENCE_NAME"]
    script_key = os.environ["SGDAEMON_LINKSHOTTOSEQUENCE_KEY"]

    args = {
        "shot_code_regex": "^([A-Za-z]{3})([0-9]{4})",
        "sequence_code_regex_group": 1,
        "sequence_code_field": "code",
        "sequence_filters": [],
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
        link_shot_to_sequence,
        {"Shotgun_Shot_Change": ["code"]},
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
        "shot_code_regex": {"type": [str], "allow_empty": False},
        "sequence_code_regex_group": {"type": [int], "allow_empty": False},
        "sequence_code_field": {"type": [str], "allow_empty": False},
        "sequence_filters": {"type": [list], "allow_empty": True},
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
        entity_schema = sg.schema_field_read("Sequence")
    except Exception as e:
        logger.warning(
            'Can\'t read SG schema for "entity_type" args\'s value ("%s"): %s'
            % (args["entity_type"], e)
        )
        return

    # Make sure seqeunce_code_field is in the entity type's schema.
    if args["sequence_code_field"] not in entity_schema:
        logger.warning(
            "%s not in entity schema, please fix." % args["sequence_code_field"]
        )
        return

    return True


def link_shot_to_sequence(sg, logger, event, args):
    """
    If Shot is missing a Sequence, update it with the correct one based on
    the naming convention.

    For details, see the description at the top of the file.

    :param sg: Shotgun API handle
    :param logger: Logger instance
    :param event: EventLogEntry entity dictionary from Shotgun
    :param args: Any additional misc arguments passed through this plugin.
    """

    # Return if we don't have all the field values we need.
    if not event.get("meta", {}).get("entity_id"):
        return

    # Make some vars for convenience.
    entity_id = event["meta"]["entity_id"]

    # Lookup the Shot.
    filters = [["id", "is", entity_id]]
    fields = ["code", "sg_sequence", "project"]
    shot = sg.find_one("Shot", filters, fields)

    # These are cases where we cannot continue.
    if not shot:
        logger.warning(
            "Unable to find Shot with id #%d in Shotgun. Exiting." % entity_id
        )
        return
    if not shot["code"]:
        logger.debug(
            "Shot (#%d) 'code' is empty, can't do anything. Exiting." % entity_id
        )
        return
    if shot["sg_sequence"]:
        logger.debug(
            "Shot '%s' (#%d) already has a linked Sequence. Exiting."
            % (shot["code"], shot["id"])
        )
        return

    # Check if the Shot code is valid.
    m = re.search(args["shot_code_regex"], shot["code"])
    if not m:
        logger.debug(
            "Shot code: %s (#%d) doesn't match valid naming convention. Exiting."
            % (shot["code"], shot["id"])
        )
        return
    sequence_code = m.group(args["sequence_code_regex_group"])

    # Lookup the Sequence.
    filters = [
        ["project", "is", shot["project"]],
        [args["sequence_code_field"], "is", sequence_code],
    ]

    # Append any additional Sequence filters from args.
    filters += args["sequence_filters"]

    sequence = sg.find_one("Sequence", filters, ["code"])
    if not sequence:
        logger.warning(
            "No Sequence found matching Sequence Code: %s. Using filters: %s. Exiting."
            % (sequence_code, filters)
        )
        return

    # Update the Shot with the correct Sequence.
    sg.update("Shot", shot["id"], {"sg_sequence": sequence})
    logger.debug(
        "Updated Shot '%s' (#%d) with Sequence '%s' (#%d)"
        % (shot["code"], shot["id"], sequence["code"], sequence["id"])
    )
