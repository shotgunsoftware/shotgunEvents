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
    script_name = os.environ["SGDAEMON_TSUES_NAME"]
    script_key = os.environ["SGDAEMON_TSUES_KEY"]

    # User-defined plugin args, change at will.
    args = {
        "task_status_field": "sg_status_list",
        "task_fin_status": "fin",
        "task_ip_status": "ip",
        "task_na_status": "na",
        "target_status_field": "sg_status_list",
        "target_fin_status": "fin",
        "target_ip_status": "ip",
        "target_disable_status": "na"
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
        update_entity_status,
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


def update_entity_status(sg, logger, event, args):
    """
    Updates an entity's status if the conditions are met.

    :param sg: Shotgun API handle.
    :param logger: Logger instance.
    :param event: A Shotgun EventLogEntry entity dictionary.
    :param args: Any additional misc arguments passed through this plugin.
    """

    if (not event.get("meta", {}).get("entity_id") and
        not event.get("meta", {}).get("old_value") and
        not event.get("meta", {}).get("new_value")):
            return

    # Make some vars for convenience.
    task_id = event["meta"]["entity_id"]
    old_value = event["meta"]["old_value"]
    new_value = event["meta"]["new_value"]

    # If the Task status has been set to task_fin_status or task_na_status...
    if new_value == args["task_fin_status"] or new_value == args["task_na_status"]:

        # Re-query the Task to gather additional field values.
        task = sg.find_one("Task", [["id", "is", task_id]], ["entity"])

        # Find all Tasks attached to the same entity. Note this will include the
        # current Task, which is probably a good thing, in case its status has
        # been changed.
        tasks = sg.find(
            "Task",
            [
                ["entity", "is", task["entity"]],
            ],
            [args["task_status_field"]],
        )

        # Determine if all those Tasks are set to fin_status.
        all_tasks_final = True
        task_na_count = 0
        for linked_task in tasks:
            if linked_task[args["task_status_field"]] == args["task_na_status"]:
                task_na_count += 1
                continue
            if linked_task[args["task_status_field"]] != args["task_fin_status"]:
                all_tasks_final = False
                break

        # Ignore Tasks set to task_na_status, unless all of them are set to na.
        if task_na_count == len(tasks):
            all_tasks_final = False

        if all_tasks_final:

            # Re-query our linked entity to get the target_status field value.
            entity = sg.find_one(
                task["entity"]["type"],
                [["id", "is", task["entity"]["id"]]],
                [args["target_status_field"], "code"],
            )

            # Update our linked entity if its target_status field value is not
            # na_status.
            if entity[args["target_status_field"]] != args["target_disable_status"]:
                sg.update(
                    entity["type"],
                    entity["id"],
                    {args["target_status_field"]: args["target_fin_status"]}
                )

                # Tell the logger all about it.
                logger.info("Updated %s %s with new %s value %s." % (
                    entity["type"],
                    entity["code"],
                    args["target_status_field"],
                    args["target_fin_status"],
                ))

    # Else if the Task status has been set to task_ip_status...
    elif new_value == args["task_ip_status"]:

        # Re-query the Task to gather additional field values.
        task = sg.find_one("Task", [["id", "is", task_id]], ["entity", args["task_status_field"]])

        # Double-check the Task is still set to task_ip_status (could have
        # changed since the event was triggered):
        if task[args["task_status_field"]] == args["task_ip_status"]:

            # Re-query our linked entity to get the target_status field value.
            entity = sg.find_one(
                task["entity"]["type"],
                [["id", "is", task["entity"]["id"]]],
                [args["target_status_field"], "code"],
            )

            # Set our parent entity to target_ip_status.
            sg.update(
                entity["type"],
                entity["id"],
                {args["target_status_field"]: args["target_ip_status"]}
            )

            # Tell the logger all about it.
            logger.info("Updated %s %s with new %s value %s." % (
                entity["type"],
                entity["code"],
                args["target_status_field"],
                args["target_ip_status"],
            ))

    # Else if the status has been set from task_fin/na_status to something
    # besides task_fin/na_status...
    elif (old_value == args["task_fin_status"] or old_value == args["task_na_status"]) \
    and (new_value != args["task_na_status"] or new_value != args["task_fin_status"]):

        # Re-query the Task to gather additional field values.
        task = sg.find_one("Task", [["id", "is", task_id]], ["entity"])

        # Re-query our linked entity to get the target_status field value.
        entity = sg.find_one(
            task["entity"]["type"],
            [["id", "is", task["entity"]["id"]]],
            [args["target_status_field"], "code"],
        )

        # Update our linked entity status if its target_status field value is
        # target_fin_status.
        if entity[args["target_status_field"]] == args["target_fin_status"]:

            sg.update(
                entity["type"],
                entity["id"],
                {args["target_status_field"]: args["target_ip_status"]}
            )

            # Tell the logger all about it.
            logger.info("Updated %s %s with new %s value %s." % (
                entity["type"],
                entity["code"],
                args["target_status_field"],
                args["target_ip_status"],
            ))
