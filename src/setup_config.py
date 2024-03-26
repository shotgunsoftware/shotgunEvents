import json
from pathlib import Path

import event_config

SETUP_FILENAME = "setup.json"

def write_config(data) -> None:
    config_path = event_config.getConfigPath()

    with open(config_path, "w") as json_f:
        json.dump(data, json_f, indent=2)

def setup() -> None:
    """
    Take the values from the setup.json and expand any relative paths. Then
    save the new json out as config.json

    Create the log dir and plugin path dirs if they don't exits

    """

    print("Setting Up Event Handler Config...")
    script_dir = Path(__file__).parent
    setup_filepath = script_dir / SETUP_FILENAME

    data = event_config.read_json(setup_filepath)

    for key, value in data['service'].items():
        if isinstance(value, str) and value.startswith('..'):
            path = script_dir / value
            path = path.resolve()
            data['service'][key] = str(path).replace('\\', '/')

    fix_paths = []
    for path in data['plugins']['paths']:
        if isinstance(path, str) and path.startswith('..'):
            abs_path = script_dir / path
            abs_path = abs_path.resolve()
            fix_paths.append(str(abs_path).replace('\\', '/'))
        else:
            fix_paths.append(path)
    data['plugins']['paths'] = fix_paths

    write_config(data=data)

    # Make the log and plugin dirs if they don't exist
    config = event_config.Config(event_config.getConfigPath())

    print("Checking Log Dir %s..." % str(config.log_dir))
    if not config.log_dir.exists():
        print("Creating Log Dir at %s" % str(config.log_dir))
        config.log_dir.mkdir(parents=True, exist_ok=True)

    for path in config.plugin_pathlib_paths:
        print("Checking Plugin Path %s" % str(path))
        if not path.exists():
            print("Creating Plugin Path %s" % str(path))
            path.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    setup()