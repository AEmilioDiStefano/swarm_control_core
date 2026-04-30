from setuptools import find_packages, setup

package_name = "swarm_control_core"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", [
            "config/robot_instances.yaml",
            "config/control_types.yaml",
            "config/control_interfaces.yaml",
            "config/camera_profiles.yaml",
        ]),
        ("share/" + package_name + "/launch", [
            "swarm_launch/swarm_bringup.launch.py",
            "swarm_launch/robot_minimal_launch.py",
            "swarm_launch/swarm_fpv_ui.launch.py",
        ]),
    ],
    install_requires=[
        "setuptools",
        "aiohttp",
        "numpy",
        "Pillow",
    ],
    zip_safe=True,
    maintainer="Vitruvian Systems",
    maintainer_email="emilio@vitruvian.systems",
    description="Community local-only swarm control package.",
    license="LicenseRef-Vitruvian-Community-1.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "add_robot_core = swarm_control_core.add_robot:main",
            "configure_robot_profile_core = swarm_control_core.configure_robot_profile:main",
            "robot_doctor_core = swarm_control_core.robot_doctor:main",
            "sync_robot_entries_core = swarm_control_core.sync_robot_entries:main",
            "swarm_fpv_ui_core = swarm_control_core.swarm_fpv_ui:main",
            "motor_driver_node_core = swarm_control_core.motor_driver_node:main",
            "swarm_camera_node_core = swarm_control_core.swarm_camera_node:main",
            "save_camera_profile_core = swarm_control_core.save_camera_profile:main",
            "unit_executor_action_server_core = swarm_control_core.unit_executor_action_server:main",
            "camera_autonomy_node_core = swarm_control_core.camera_autonomy_node:main",
            "heartbeat_node_core = swarm_control_core.heartbeat_node:main",
            "swarm_teleop_core = swarm_control_core.swarm_teleop:main",
            "terminal_playbook_runner_core = swarm_control_core.terminal_playbook_runner:main",
        ],
    },
)
