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
    script_name = os.environ["SGDAEMON_TASKSAPPROVED_NAME"]
    script_key = os.environ["SGDAEMON_TASKSAPPROVED_KEY"]

    args = {
        "task_status_field": "sg_status_list",
        "task_status": ["fin"],
        "upstream_tasks_field": "upstream_tasks",
        "downstream_tasks_field": "downstream_tasks",
        "downstream_task_status_activate": ["wtg"],
        "downstream_task_status_active": "ip",
        "downstream_task_status_recurse": ["na"],
        "note_status_field": "sg_status_list",
        "close_notes": True,
        "closed_note_status": "clsd",
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
        tasks_approved,
        {"Shotgun_Task_Change": args["task_status_field"]},
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


def tasks_approved(sg, logger, event, args):
    """
    Handles the logic to approve a Task and update associated entities.

    :param sg: Shotgun API object handle.
    :param logger: Logging object.
    :param event: Event object.
    :param args: Any args that have been passed in from the callback.
    """

    # Return if we don't have all the field values we need.
    if not event.get("meta", {}).get("entity_id"):
        return

    # Make some vars for convenience.
    entity_id = event["meta"]["entity_id"]

    # Re-query the Task to gather extra field values.
    task = sg.find_one(
        "Task",
        [["id", "is", entity_id]],
        [args["task_status_field"], args["downstream_tasks_field"]],
    )

    # Return if no Task is found (this can happen when the Task is deleted).
    if not task:
        logger.debug("Could not find Task ID %s" % entity_id)
        return

    # Return if our Task isn't set to a valid task_status.
    elif task[args["task_status_field"]] not in args["task_status"]:
        logger.debug(
            "Task with ID %s not set to one of %s, skipping." % (task["id"], args["task_status"])
        )
        return

    # Init our SG batch update list variable.
    batch_updates = []

    # Get downstream tasks that need to be updated.
    build_updates_for_downstream_tasks(sg, logger, task, batch_updates, args)

    # Find any Notes linked to the current Task and close them.
    if args.get("close_notes") and args.get("note_status_field") and args.get("closed_note_status"):
        notes = sg.find(
            "Note",
            [["tasks.Task.id", "is", task["id"]]],
            ["tasks", args["note_status_field"]],
        )
        for note in notes:
            if all_note_tasks_approved(sg, note, args):
                batch_updates.append({
                    "request_type": "update",
                    "entity_type": "Note",
                    "entity_id": note["id"],
                    "data": {args["note_status_field"]: args["closed_note_status"]},
                })

    # If we have something to do, do it!
    if batch_updates:
        sg.batch(batch_updates)
        logger.info(
            "All Notes attached to Task with ID %s will be set to \"%s\"." % (
                task["id"], args["closed_note_status"]
            )
        )
    else:
        logger.info("Task with ID %s: nothing to do, skipping." % task["id"])


def build_updates_for_downstream_tasks(sg, logger, task, batch_updates, args):
    """
    Loop through our downstream tasks and append any necessary updates to the
    batch_updates list.

    :param sg: A Shotgun API handle object.
    :param task: A Shotgun Task dictionary.
    :param batch_updates: A list sent to a Shotgun API batch command.
    :param args: A Dict of user args.
    """

    # Return if there are no downstream tasks.
    if not task.get(args["downstream_tasks_field"]):
        return

    # Re-query all the downstream Tasks to gather their status and downstream
    # tasks values.
    downstream_tasks = sg.find(
        "Task",
        [
            ["id", "in", [t["id"] for t in task[args["downstream_tasks_field"]]]]
        ],
        [
            args["task_status_field"],
            args["upstream_tasks_field"],
            args["downstream_tasks_field"],
        ],
    )

    # Loop through our downstream tasks and append any necessary Task status
    # updates to the batch_updates list.
    for downstream_task in downstream_tasks:

        # Make sure all upstream Tasks are also set to a valid status.
        upstream_check = True
        if len(downstream_task[args["upstream_tasks_field"]]) > 1:
            for upstream_task in downstream_task[args["upstream_tasks_field"]]:
                upstream_task = sg.find_one(
                    "Task",
                    [["id", "is", upstream_task["id"]]],
                    ["sg_status_list"],
                )
                if upstream_task["sg_status_list"] not in args["task_status"] \
                and upstream_task["sg_status_list"] not in args["downstream_task_status_recurse"]:
                    upstream_check = False
                    break
        if not upstream_check:
            continue

        if downstream_task.get(args["task_status_field"]) in \
        args["downstream_task_status_activate"]:

            batch_updates.append({
                "request_type": "update",
                "entity_type": "Task",
                "entity_id": downstream_task["id"],
                "data": {
                    args["task_status_field"]: args["downstream_task_status_active"]
                },
            })
        elif args.get("downstream_task_status_recurse") \
        and downstream_task.get(args["task_status_field"]) in \
        args["downstream_task_status_recurse"]:
            build_updates_for_downstream_tasks(sg, logger, downstream_task, batch_updates, args)


def all_note_tasks_approved(sg, note, args):
    """
    Determine if all Notes on the relevent Task have been approved.

    :param sg: A Shotgun API handle object.
    :param note: A Shotgun Note dictionary.
    :param args: A dict of plugin args.
    :returns: True if all Notes on the relevant Task have been approved, False
              otherwise.
    """

    # Re-query all Tasks attached to the Note to gather note_status_field values.
    note_tasks = sg.find(
        "Task",
        [["id", "in", [t["id"] for t in note.get("tasks")]]],
        [args["note_status_field"]],
    )

    # Loop through all Tasks attached to the Note and return False if any
    # note_status_field values are not equal to our task_status.
    for note_task in note_tasks:
        if note_task.get(args["note_status_field"]) != args["task_status"]:
            return False

    return True
