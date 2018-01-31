# Copyright 2018 Autodesk, Inc.  All rights reserved.
#
# Use of this software is subject to the terms of the Autodesk license agreement
# provided at the time of installation or download, or which otherwise accompanies
# this software in either electronic or hard copy form.
#

import os
import shotgun_api3

"""
This plugin was created for the Shotgun Developer Learning series video titled,
"The Shotgun Event Daemon." See this page for details:

https://support.shotgunsoftware.com/hc/en-us/articles/115002525494-SG-Learning-Developer-Training

This plugin has not been code-reviewed, QA'd, or used in production. It was
written primarily to teach developers how to write plugins and avoid common
pitfalls. Use/modify at your own risk.

When an entity's args["entity_status_field"] field changes to
args["target_status"], its description field is updated (if it's empty) with the
name of the user who put it On Hold, and its child Tasks args["entity_status_field"]
fields are set to args["target_status"], unless they're already set to a status
in args["skip_statuses"]. If you'd like to change this plugin's behavior, modify
the "args" in the registerCallbacks function.
"""


def registerCallbacks(reg):
    """
    This function is run when the Shotgun Event Daemon starts, if this file
    (__file__) lives in the plugin directory specified by the daemon's config
    file. Typically the registerCallback method should be called from the
    available reg object.

    :param object reg: A registrar object instance that can be used to register
                       a Callback function with the daemon.
    """

    # User-defined plugin args, change at will.
    args = {
        "target_status": "hld",
        "entity_status_field": "sg_status_list",
        "entity_type": "Asset",
        "skip_statuses": ["fin", "na", "hld"],
    }

    # Grab authentication env vars for this plugin. Install these into the env
    # if they don't already exist.
    server = os.environ["SG_SERVER"]
    script_name = os.environ["SGDAEMON_ESUTS_NAME"]
    script_key = os.environ["SGDAEMON_ESUTS_KEY"]

    # Grab an sg connection for the validator.
    sg = shotgun_api3.Shotgun(server, script_name=script_name, api_key=script_key)

    # Bail if our validator fails.
    if not is_valid(sg, reg.logger, args):
        reg.logger.warning("Plugin is not valid, will not register callback.")
        return

    # We are only interested in changes to args["entity_type"] entities'
    # args["entity_status_field"] fields.
    eventFilter = {
        "Shotgun_%s_Change" % args["entity_type"]: args["entity_status_field"],
    }

    # Register our function with the dameon, and pass in our args.
    reg.registerCallback(
        script_name,
        script_key,
        entity_status_update_task_status,
        eventFilter,
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

    # Make sure args["entity_status_field"] is still in our entity schema.
    try:
        entity_schema = sg.schema_field_read(
            args["entity_type"],
            field_name=args["entity_status_field"],
        )
    except Exception, e:
        logger.warning(
            "%s does not exist in %s schema, skipping: %s" % (
                args["entity_status_field"],
                args["entity_type"],
                e.message,
            )
        )
        return

    # Make sure args["target_status"] is in the entity schema.
    if args["target_status"] not in entity_schema["sg_status_list"]["properties"]["valid_values"]["value"]:
        logger.warning(
            "%s is not in %s schema, plugin will never execute." % (
                args["target_status"],
                args["entity_type"],
            )
        )
        return

    # Make sure the Task schema has an args["target_status"] field.
    task_schema = sg.schema_field_read(
        "Task",
        field_name="sg_status_list",
    )
    if args["target_status"] not in task_schema["sg_status_list"]["properties"]["valid_values"]["value"]:
        logger.warning("%s is not in Task schema, plugin will never execute." % args["task_status"])
        return

    return True


def entity_status_update_task_status(sg, logger, event, args):
    """
    Parses a Shotgun_[entity]_Change args["entity_status_field"] EventLogEntry,
    and if the new_value is set to args["target_status"], child Tasks are
    updated to args["target_status"], unless they're already set to a value in
    args["skip_statuses"].

    :param object sg: An authenticated Shotgun Python API instance.
    :param object logger: A standard logger instance.
    :param dict event: Data related to a Shotgun EventLogEntry.
    :param dict args: Additional user-defined settings.
    :returns: None if the event can not be processed.
    """

    # Make some vars for convenience.
    field_name = event.get("attribute_name")
    entity = event.get("entity")
    project = event.get("project")
    new_value = event.get("meta", {}).get("new_value")
    user = event.get("user")
    event_id = event.get("id")

    # Make sure all our event keys contain values.
    if None in [event_id, field_name, entity, project, new_value, user]:
        logger.warning("Missing info in event dictionary, skipping.")
        return

    # Bail if new_value isn't what we're looking for.
    if not new_value == args["target_status"]:
        logger.debug("new_value is %s, not %s, skipping." % (new_value, args["target_status"]))
        return

    # Make sure the event exists in Shotgun.
    sg_event = sg.find_one(
        "EventLogEntry",
        [["id", "is", event_id]],
        ["description"],
    )
    if not sg_event:
        logger.warning("Could not find event with id %s, skipping." % event_id)
        return

    # Spit out a nice little note for the logger.
    logger.info("Running this plugin because %s." % sg_event["description"])

    # Re-query our entity for updated field values.
    entity = sg.find_one(
        entity["type"],
        [["id", "is", entity["id"]]],
        [field_name, "description"],
    )

    # Bail if our entity doesn't exist.
    if not entity:
        logger.warning(
            "%s with id %s does not exist, skipping." % (
                entity["type"],
                entity["id"],
            )
        )
        return

    # Bail if our entity's field value has changed (is not new_value).
    if not entity[field_name] == new_value:
        logger.warning(
            "%s with id %s's %s has changed from %s since event inception." % (
                entity["type"],
                entity["id"],
                field_name,
                new_value,
            )
        )
        return

    # Init a list for an sg.batch command, and a list for collecting messages.
    batch_data = []
    update_message = []

    # Cue up a change to our entity's description field if our entity's
    # new_value is args["target_status"] and its description is None.
    if not entity["description"]:
        update_message.append("%s with id %s" % (entity["type"], entity["id"]))
        batch_data.append(
            {
                "request_type": "update",
                "entity_type": entity["type"],
                "entity_id": entity["id"],
                "data": {
                    "description": "%s set this %s to %s." % (
                        user["name"],
                        entity["type"],
                        args["target_status"],
                    )
                }
            }
        )

    # Find all the Tasks linked to our entity.
    tasks = sg.find(
        "Task",
        [["entity", "is", entity]],
        ["sg_status_list"],
    )

    # Cue up a change to all our Tasks. Set them to args["target_status"].
    for task in tasks:
        if task["sg_status_list"] not in args["skip_statuses"]:
            update_message.append("Task with id %s" % task["id"])
            batch_data.append(
                {
                    "request_type": "update",
                    "entity_type": "Task",
                    "entity_id": task["id"],
                    "data": {"sg_status_list": args["target_status"]},
                }
            )

    # Run the API batch command and tell the logger about it.
    logger.info(
        "Running batch API command to update the following: %s..." % ", ".join(update_message)
    )
    sg.batch(batch_data)
    logger.info("Done.")
