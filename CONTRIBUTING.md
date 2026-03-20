# Contributing

Thanks for helping improve `swarm_control_core`.

## How To Contribute

- open an issue for bugs, regressions, documentation gaps, or proposed features
- open a pull request for focused changes with a clear user-facing purpose
- keep docs and ADRs in sync when runtime behavior or operator workflow changes
- run the relevant build and test steps before opening a pull request

## Development Notes

- Target environment: Ubuntu 24.04 plus ROS 2 Jazzy
- Build the package with:

```bash
colcon build --packages-select swarm_control_core
```

- Run tests with:

```bash
pytest -q src/swarm_control_core/test
```

## Contribution Terms

By submitting a contribution, pull request, issue attachment, patch, or other
material intended for inclusion in this repository, you confirm that:

- you have the legal right to submit the contribution;
- your contribution does not knowingly violate the rights of another person or
  entity;
- you are submitting the contribution under this repository's contribution
  terms;
- if your contribution is accepted, Vitruvian Systems LLC receives a
  perpetual, worldwide, irrevocable, non-exclusive, royalty-free right to use,
  reproduce, modify, prepare derivative works of, distribute, sublicense,
  publicly display, publicly perform, commercialize, and otherwise exploit the
  accepted contribution as part of this project and related products,
  services, and commercial offerings;
- unless otherwise agreed in writing, you retain copyright in your own
  contribution;
- you are not entitled to financial compensation, royalties, profit-sharing,
  equity, or other monetary payment for your contribution unless separately
  agreed in writing.

By submitting a contribution, you acknowledge that accepted contributions may
be incorporated into this project and related commercial offerings by
Vitruvian Systems LLC. Contributors may receive public credit and other
non-monetary recognition described in this repository, but contributors are
not entitled to financial compensation, royalties, or profit-sharing unless
separately agreed in writing.

## Recognition

Accepted contributors may receive public credit and non-monetary career-support
benefits described in:

- [CONTRIBUTOR_BENEFITS.md](./CONTRIBUTOR_BENEFITS.md)
- [CONTRIBUTORS.md](./CONTRIBUTORS.md)

## Before Opening A Pull Request

- make sure the package builds cleanly
- run the relevant tests
- explain the user-facing reason for the change
- update docs or ADRs when behavior changes
