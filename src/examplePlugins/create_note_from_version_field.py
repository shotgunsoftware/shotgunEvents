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
    Register our callbacks
    :param reg: A Registrar instance provided by the event loop handler
    """

    # Grab authentication env vars for this plugin. Install these into the env
    # if they don't already exist.
    server = os.environ["SG_SERVER"]
    script_name = os.environ["SGDAEMON_CNFVF_NAME"]
    script_key = os.environ["SGDAEMON_CNFVF_KEY"]

    args = {
        "sg_note_type": "Client",
        "content_field": "description",
        "author_is_artist": True,
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
        version_content_changed,
        {"Shotgun_Version_Change": args["content_field"]},
        args,
    )


def is_valid(sg, logger, args):
    """
    Validate our args.

    :param sg: Shotgun API handle.
    :param logger: Logger instance.
    :param args: Any additional misc arguments passed through this plugin.
    :returns: True if plugin is valid, None if not.
    """

    args_to_check = {
        "sg_note_type": {"type": [str], "allow_empty": False},
        "content_field": {"type": [str], "allow_empty": False},
        "author_is_artist": {"type": [bool], "allow_empty": False},
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

    # Make sure we can read the Version schema.
    try:
        version_schema = sg.schema_field_read("Version")
    except Exception as e:
        logger.warning(
            'Can\'t read SG schema for "entity_type" args\'s value ("%s"): %s'
            % (args["entity_type"], e)
        )
        return

    # Make sure content_field is in the entity type's schema.
    if args["content_field"] not in version_schema:
        logger.warning("%s not in Version schema, please fix." % args["content_field"])
        return

    # Make sure we can read the Version schema.
    try:
        note_schema = sg.schema_field_read("Note")
    except Exception as e:
        logger.warning(
            'Can\'t read SG schema for "entity_type" args\'s value ("%s"): %s'
            % (args["entity_type"], e)
        )
        return

    valid_note_types = note_schema["sg_note_type"]["properties"]["valid_values"][
        "value"
    ]

    # Make sure content_field is in the entity type's schema.
    if args["sg_note_type"] not in valid_note_types:
        logger.warning(
            "%s not in Note schema. Valid types are %s, please fix."
            % (args["sg_note_type"], valid_note_types,)
        )
        return

    return True


def version_content_changed(sg, logger, event, args):
    """
    First, get the value of a Version's {content_field} field when it
    changes, along with some other data related to the Version.
    Second, Create a Note from the data retrieved from the Version.

    :param sg: Shotgun API instance.
    :param logger: Standard Event loop logger.
    :param event: ShotgunEvent this trigger is listening for.
    :param args: Additional arguments registerd for this trigger.
    """

    # Return if there's no entity or entity id.
    if not event.get("entity", {}).get("id") or not event.get("user"):
        return

    # Make some vars for convenience.
    entity_id = event["entity"]["id"]
    user = event["user"]

    # Re-query the Version to gather additional field values.
    version = sg.find_one(
        "Version",
        [["id", "is", entity_id]],
        ["sg_task", "entity", args["content_field"], "project", "code", "user"],
    )

    # Return if we can't find our Version.
    if not version:
        logger.info(
            "Could not find Version with id %s for event %d, skipping."
            % (entity_id, event["id"])
        )
        return

    # Return if there is no content to create the Note with.
    if not version[args["content_field"]]:
        logger.debug(
            "%s field value is empty on Version with id %s, skipping."
            % (args["content_field"], version["id"])
        )
        return

    # user = the Version artist if author_is_artist is True and the Verion's
    # user field is not empty.
    if args["author_is_artist"] and version["user"]:
        user = version["user"]

    # If user turns out to be a HumanUser, requery and use firstname.
    if user["type"] == "HumanUser":
        user = sg.find_one("HumanUser", [["id", "is", user["id"]]], ["firstname"])
        user_name = user["firstname"]
    else:
        user_name = user["name"]

    # Create a Note using data from the Version.
    try:

        data = {
            "project": version["project"],
            "user": user,
            "content": version[args["content_field"]],
            "sg_note_type": args["sg_note_type"],
            "suppress_email_notif": True,
        }
        if version["sg_task"]:
            data["tasks"] = [version["sg_task"]]
        if version["entity"]:
            entity = sg.find_one(
                version["entity"]["type"],
                [["id", "is", version["entity"]["id"]]],
                ["code"],
            )
            data["note_links"] = [entity, version]
            data["subject"] = "%s's Note on %s and %s" % (
                user_name,
                version["code"],
                entity["code"],
            )
        else:
            data["note_links"] = [version]
            data["subject"] = "%s's Note on %s" % (user_name, version["code"])
        note = sg.create("Note", data)
        logger.debug("Result is: %s" % note)
        logger.info("Created Note with id %s." % note["id"])

    except Exception as e:
        logger.error(
            "Could not create Note from Version with id %s: %s"
            % (version["id"], str(e))
        )
