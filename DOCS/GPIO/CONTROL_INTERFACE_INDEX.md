# Control Interface Index

Generated from `config/control_interfaces.yaml`. Do not hand-maintain profile details here;
update the YAML source of truth and regenerate this file.

| Interface | Compatible Control Types | Backend | Layout | Controller | Wiring Doc |
| --- | --- | --- | --- | --- | --- |
| `l298n_diff` | diff_drive | gpio_hbridge | side_pair | 1 x L298N | [`DOCS/GPIO/GPIO_for_differential_L298N.md`](./GPIO_for_differential_L298N.md) |
| `dual_l298n_diff` | diff_drive | gpio_hbridge | four_wheel | 2 x L298N | [`DOCS/GPIO/GPIO_for_differential_DUAL_L298N.md`](./GPIO_for_differential_DUAL_L298N.md) |
| `dual_l298n_mecanum` | mecanum_drive | gpio_hbridge | four_wheel | 2 x L298N | [`DOCS/GPIO/GPIO_for_mecanum_DUAL_L298N.md`](./GPIO_for_mecanum_DUAL_L298N.md) |
| `dual_tb6612_mecanum` | mecanum_drive | gpio_hbridge | four_wheel | 2 x TB6612 | [`DOCS/GPIO/GPIO_for_mecanum_Tb6612_DUAL.md`](./GPIO_for_mecanum_Tb6612_DUAL.md) |
| `dual_tb6612_diff_4wheel_tracked` | diff_drive | gpio_hbridge | front_pair | 2 x TB6612 | [`DOCS/GPIO/GPIO_for_differential_Tb6612_DUAL.md`](./GPIO_for_differential_Tb6612_DUAL.md) |
