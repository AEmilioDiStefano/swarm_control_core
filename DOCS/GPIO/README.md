# GPIO Wiring Guides

Use these wiring references for the hardware-side GPIO mappings that back the
core robot drive profiles:

- [`CONTROL_INTERFACE_INDEX.md`](./CONTROL_INTERFACE_INDEX.md) is generated from
  `config/control_interfaces.yaml` and points maintainers back to the YAML
  source of truth.
- Each control-interface entry in `config/control_interfaces.yaml` uses
  `docs.wiring` to point at the correct wiring guide in this directory.

Add or change the YAML first, then add a wiring guide only when the new
interface needs one.
