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
    script_name = os.environ["SGDAEMON_UTTE_NAME"]
    script_key = os.environ["SGDAEMON_UTTE_KEY"]

    # Here's the rationale for these wacky defaults:
    # - 70 is the id of a demo Project that ships with Shotgun.
    # - The Asset entity type is commonly used.
    # - The entity_type field on the TaskTemplate entity can't be deleted.
    args = {
        "project_ids": [97],
        "entity_types": ["Asset"],
        "plugins_field": "sg_plugins",
        "plugins_field_value": "Update linked entities",
        "trash_old_tasks": True,
        "overwrite_field_values": True,
        "exclude_fields": ["task_assignees", "start_date", "due_date", "duration"],
    }

    # Grab an sg connection for the validator.
    sg = shotgun_api3.Shotgun(server, script_name=script_name, api_key=script_key)

    # Bail if our validator fails.
    if not is_valid(sg, reg.logger, args):
        reg.logger.warning("Plugin is not valid, will not register callback.")
        return

    # Register our callback.
    reg.registerCallback(
        script_name,
        script_key,
        update_entities,
        {"Shotgun_TaskTemplate_Change": args["plugins_field"]},
        args,
    )


def is_valid(sg, logger, args):
    """
    Validate our args.

    :param reg: A PluginRegistrar instance.
    """

    # Define our check-args list.
    args_to_check = {
        "project_ids": {"type": [list], "allow_empty": False},
        "entity_types": {"type": [list], "allow_empty": False},
        "plugins_field": {
            "type": [str],
            "allow_empty": False,
            "entity": "TaskTemplate",
            "sg_type": ["list", "entity_type"],
            "required_values": ["N/A", args["plugins_field_value"]],
        },
        "plugins_field_value": {"type": [str], "allow_empty": False},
        "trash_old_tasks": {"type": [bool], "allow_empty": False},
        "overwrite_field_values": {"type": [bool], "allow_empty": False},
        "exclude_fields": {"type": [list], "allow_empty": True},
    }

    # Check our args.
    for name, checks in args_to_check.items():

        # Grab the setting's value type.
        value_type = type(args[name])

        # We assume unicode and str to be equivalent for these checks because
        # args come back from Django as unicode but are first set by the
        # Registrar as str.
        if value_type.__name__ == "unicode":
            value_type = str

        # Make sure the setting value is the correct Python type.
        if checks.get("type") and value_type not in checks["type"]:
            logger.warning(
                '"%s" setting\'s value is %s but should be %s, please fix.'
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

            # Perform some standard checks on the entity and field.
            if not check_entity_schema(
                sg,
                logger,
                checks["entity"],
                args[name],
                checks["sg_type"],
                checks["required_values"],
            ):
                return

    # Make sure the Project(s) the user references exist.
    projects = sg.find("Project", [["id", "in", args["project_ids"]]])
    project_ids = [i["id"] for i in projects]
    for project_id in args["project_ids"]:
        if project_id not in project_ids:
            logger.warning(
                "Project with id %s does not exist, please fix." % project_id
            )
            return

    # Make sure the fields the user wants to exclude exist.
    task_schema = sg.schema_field_read("Task")
    for field in args["exclude_fields"]:
        if field not in task_schema.keys():
            logger.warning("Field %s is not in the Task schema, please fix." % field)
            return

    # Make sure the entity types the user specifies exist.
    for entity_type in args["entity_types"]:
        try:
            sg.schema_field_read(entity_type)
        except:
            logger.warning(
                "Could not read schema for entity type %s, please fix." % entity_type
            )
            return

    return True


def check_entity_schema(
    sg, logger, entity_type, field_name, field_types, required_values
):
    """
    Verifies that field_name of field_type exists in entity_type's schema.

    :param sg: An authenticated Shotgun Python API instance.
    :param entity_type: str, a Shotgun entity type.
    :param field_name: str, the name of a field on entity_type.
    :param field_types: list, the Shotgun field types that field_name should be.
    :param required_values: list, values that must exist if the field Shotgun
                            type is a list or status list.
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
            '%s entity %s field "%s" does not exist in Shotgun, please fix.'
            % (entity_type, field_types, field_name,)
        )
        return

    # Make sure the field is the correct Shotgun type.
    if sg_type not in field_types:
        logger.warning(
            'SG field "%s" is type "%s" but should be of type(s) "%s," please fix.'
            % (field_name, sg_type, field_types,)
        )
        return

    # If we have a list or status_list Shotgun field, make sure any required
    # values exist.
    if sg_type == "list" or sg_type == "status_list":
        schema_list_values = (
            entity_schema.get(field_name, {})
            .get("properties", {})
            .get("valid_values", {})
            .get("value", [])
        )
        missing_values = []
        for value in required_values:
            if value not in schema_list_values:
                missing_values.append(value)
        if missing_values:
            logger.warning(
                'SG field "%s" does not contain required value(s) "%s", please fix.'
                % (field_name, missing_values,)
            )
            return

    return True


def update_entities(sg, logger, event, args):
    """
    Loops over the user-specified summarize items, summarizes them and then
    combines them according to their operator types. Finally, the result is
    stored on the linked entity's field_to_update field.

    :param sg: SG API handle
    :param logger: Logger instance
    :param dict event: SG EventLogEntry
    :param dict args: Django args
    """

    # Return if we don't have all the info we need.
    if not event.get("entity", {}).get("id"):
        return

    # Re-query our Task Template.
    task_template = sg.find_one("TaskTemplate", [["id", "is", event["entity"]["id"]]],)

    # Bail if we don't have a Task Template.
    if not task_template:
        logger.error("No Task Template found, skipping.")
        return

    # Set the plugin switch to N/A before doing anything.
    sg.update("TaskTemplate", task_template["id"], {args["plugins_field"]: "N/A"})

    # Grab the Task schema.
    task_schema = sg.schema_field_read("Task")

    # Remove any Task fields from the schema that we aren't allowed to edit.
    task_schema_copy = task_schema.copy()
    for field, value in task_schema.items():
        if value["editable"]["value"] is False:
            del task_schema_copy[field]
    task_schema = task_schema_copy

    # Grab all the Tasks in the template.
    template_tasks = sg.find(
        "Task", [["task_template", "is", task_template]], task_schema.keys(),
    )

    # Grab Project records based on project_ids args.
    projects = sg.find("Project", [["id", "in", args["project_ids"]]])

    # Bail if we don't have any Projects.
    if not projects:
        logger.error("No Projects found based on project_ids list, skipping.")
        return

    # Bail if we don't have a Task Template.
    if not task_template:
        logger.error("Task Template could not be found, skipping.")
        return

    # Init out batch_data list.
    batch_data = []
    batch_delete_data = []

    # Loop over entity types.
    for entity_type in args["entity_types"]:

        # Grab all entities attached to the Task Template in relevant Projects.
        entities = sg.find(
            entity_type,
            [["task_template", "is", task_template], ["project", "in", projects],],
            ["project"],
        )

        # Loop over the entities.
        for entity in entities:

            # Grab all the Tasks on the entity.
            tasks = sg.find(
                "Task",
                [["entity", "is", entity]],
                task_schema.keys() + ["template_task"],
            )

            # Loop over the entity's Tasks.
            for task in tasks:

                in_template = False

                # Loop over the Task Template Tasks.
                for template_task in template_tasks:

                    # If the Task has no associated Template Task, skip it.
                    if not task["template_task"]:
                        continue

                    # Keep going if the linked TaskTemplate matches.
                    if task["template_task"]["id"] == template_task["id"]:

                        # Set our in_template flag if a match is found.
                        in_template = True

                        # Gather non-empty field info in our template_data dict.
                        template_data = {}
                        for field, value in template_task.items():
                            if value and field in task_schema.keys():
                                template_data[field] = value

                        # Init our data update dict.
                        data = {}

                        # Loop over the fields.
                        for field, value in task.items():

                            # Determine if we're going to write the value.
                            write_value = False
                            if not value:
                                write_value = True
                            elif (
                                value
                                and args["overwrite_field_values"]
                                and field not in args["exclude_fields"]
                            ):
                                write_value = True
                            if not write_value:
                                continue

                            # Queue up the value.
                            if template_data.get(field):
                                data[field] = template_data[field]

                        # This is not a template anymore, so nix that bit.
                        del data["task_template"]

                        # Update the Task.
                        batch_data.append(
                            {
                                "request_type": "update",
                                "entity_type": "Task",
                                "entity_id": task["id"],
                                "data": data,
                            }
                        )
                        logger.info("Will update Task with id %s." % task["id"])

                # If a Task on the entity isn't in the Template and
                # trash_old_tasks is True, delete the Task and tell the logger.
                if not in_template and args["trash_old_tasks"]:
                    batch_delete_data.append(
                        {
                            "request_type": "delete",
                            "entity_type": "Task",
                            "entity_id": task["id"],
                        }
                    )
                    logger.info("Will delete Task with id %s." % task["id"])

            # Loop over the template Tasks.
            for template_task in template_tasks:

                assigned_to_entity = False

                # Loop over the Tasks on the entity.
                for task in tasks:

                    # If the Task has no associated Template Task, skip it.
                    if not task["template_task"]:
                        continue

                    # Set our assigned_to_entity flag if a match is found.
                    if task["template_task"]["id"] == template_task["id"]:
                        assigned_to_entity = True

                # Add any non-empty field info to our data dict.
                data = {}
                for field, value in template_task.items():
                    if value and field in task_schema.keys():
                        data[field] = value

                # Add the entity and Project.
                data["entity"] = entity
                data["project"] = entity["project"]
                data["template_task"] = template_task

                # This is not a template anymore, so nix that bit.
                del data["task_template"]

                # If the Task doesn't exist on the entity, add it.
                if not assigned_to_entity:
                    batch_data.append(
                        {"request_type": "create", "entity_type": "Task", "data": data,}
                    )
                    logger.info(
                        "Will create %s Task on entity with id %s."
                        % (template_task["content"], entity["id"],)
                    )

    # And now the scary part.
    if batch_data:
        sg.batch(batch_data)
        logger.info("Completed batch create/update.")
    if batch_delete_data:
        sg.batch(batch_delete_data)
        logger.info("Completed batch delete.")
