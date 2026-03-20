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
            "config/robot_profiles.yaml",
            "config/robot_instances.yaml",
            "config/control_types.yaml",
            "config/control_interfaces.yaml",
            "config/capability_profiles.yaml",
            "config/adapter_profiles.yaml",
            "config/camera_profiles.yaml",
        ]),
        ("share/" + package_name + "/launch", [
            "launch/swarm_bringup.launch.py",
            "launch/robot_minimal.launch.py",
            "launch/swarm_fpv_ui.launch.py",
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
            "swarm_fpv_ui_com = swarm_control_core.swarm_fpv_ui:main",
            "motor_driver_node_com = swarm_control_core.motor_driver_node:main",
            "swarm_camera_node_com = swarm_control_core.swarm_camera_node:main",
            "save_camera_profile_com = swarm_control_core.save_camera_profile:main",
            "unit_executor_action_server_com = swarm_control_core.unit_executor_action_server:main",
            "camera_autonomy_node_com = swarm_control_core.camera_autonomy_node:main",
            "heartbeat_node_com = swarm_control_core.heartbeat_node:main",
            "swarm_teleop_com = swarm_control_core.swarm_teleop:main",
            "terminal_orchestrator_com = swarm_control_core.terminal_orchestrator:main",
        ],
    },
)
