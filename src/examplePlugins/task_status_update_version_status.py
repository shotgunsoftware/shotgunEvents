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
    script_name = os.environ["SGDAEMON_TSUVS_NAME"]
    script_key = os.environ["SGDAEMON_TSUVS_KEY"]

    # User-defined plugin args, change at will.
    args = {"status_mapping_field": "sg_version_status_mapping"}

    # Grab an sg connection for the validator.
    sg = shotgun_api3.Shotgun(server, script_name=script_name, api_key=script_key)

    # Bail if our validator fails.
    if not is_valid(sg, reg.logger, args):
        reg.logger.warning("Plugin is not valid, will not register callback.")
        return

    reg.registerCallback(
        script_name,
        script_key,
        task_status_changed,
        {"Shotgun_Task_Change": ["sg_status_list"]},
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

    # Make sure we have a valid sg connection.
    try:
        sg.find_one("Project", [])
    except Exception as e:
        logger.warning(e)
        return

    return True


def task_status_changed(sg, logger, event, args):
    """
    First, get the Task status value the HumanUser has set.
    Second, get the latest Version whose Task field includes the current task.
    Third, update that Version's Status field via the mapping field.

    :param sg: Shotgun API instance.
    :param logger: Standard Event loop logger.
    :param event: ShotgunEvent this trigger is listening for.
    :param args: Additional arguments registerd for this trigger.
    """

    # Return if we don't have all the field values we need.
    if (not event.get("entity", {}).get("id") or
        not event.get("meta", {}).get("entity_id") or
        not event.get("id")):
            return

    # Make some vars for convenience.
    entity_id = event["entity"]["id"]
    entity_name = event["entity"]["name"]
    status_mapping_field = args["status_mapping_field"]

    # Re-query for the Task Status value to make sure we have an up-to-date
    # new status value. The input value from the event may be inaccurate if the
    # triggers are ever running behind.
    sg_task = sg.find_one(
        "Task",
        [["id", "is", entity_id]],
        ["sg_status_list"]
    )

    # Return if we can't find our Task.
    if not sg_task:
        logger.info(
            "Unable to retrieve Task (%d) %s from SG for event %d, skipping." %
            (entity_id, entity_name, event["id"])
        )
        return

    # Grab the Shotgun Status entity the Task was set to.
    new_task_status = sg.find_one(
        "Status",
        [["code", "is", sg_task["sg_status_list"]]],
        [status_mapping_field],
    )

    # Return if we can't find our Status entity (would be pretty weird).
    if not new_task_status:
        logger.info("No Status found with code %s, skipping." % sg_task["sg_status_list"])
        return

    # Return if the Status entity's sg_version_status_mapping value is empty.
    if new_task_status[status_mapping_field] is None:
        logger.debug(
            "No sg_version_status_mapping found for Status with id %s, skipping." % new_task_status["id"]
        )
        return

    # Get the latest Version attached to our Task.
    sg_version = sg.find_one(
        "Version",
        [["sg_task", "is", sg_task]],
        [],
        order=[{"field_name": "created_at", "direction": "desc"}],
    )

    # Return if we can't find a Version attached to the Task.
    if not sg_version:
        logger.debug("No Version linked to Task with id %s, skipping." % entity_id)
        return

    # Update the Version's sg_status_field with the Status entity's
    # sg_version_status_mapping value.
    try:
        result = sg.update(
            "Version",
            sg_version["id"],
            {"sg_status_list": new_task_status[status_mapping_field]},
        )
        logger.debug("Result is: %s" % result)
    except Exception as e:
        logger.warning(
            "Could not update Version with id %s to Status %s: %s" % (
                sg_version["id"],
                new_task_status[status_mapping_field],
                str(e)
            )
        )
