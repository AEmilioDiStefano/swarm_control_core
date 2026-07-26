# Intellectual Property Protection — swarm_control_core

**Audience:** users, evaluators, collaborators, and prospective investors.
**Purpose:** to state plainly how Vitruvian Systems LLC protects the
intellectual property behind the `swarm_control` product line. This document
is public by design and deliberately contains **no** confidential technical
detail; it describes *that* our IP is protected and *how the protection is
structured*, not the protected material itself.

---

## What this repository is — and is not

`swarm_control_core` is a **public but proprietary** package. It is
source-available for evaluation, learning, and local demonstration, and it
serves as the shared, deliberately-bounded foundation for the broader
`swarm_control` ecosystem. It is **not** open source and **not** a grant of
the company's core intellectual property.

- Use is governed by the [Vitruvian Community License](./LICENSE), a
  limited-use license. Personal, academic, internal-evaluation, and
  small-entity use are permitted on stated terms; commercial deployment beyond
  those terms requires a separate written commercial license.
- Making the foundation public is a strategic choice: it lets us showcase
  capability, invite collaboration, and prove the system on a local network —
  **without** exposing the innovations that make the product defensible.

## The core protection principle: value lives behind a boundary, not in obscurity

The design of the product line is itself the first layer of IP protection. The
capabilities that constitute the company's defensible intellectual property —
the formalized control model, the heterogeneous-asset orchestration logic, the
remote-operations architecture, and the security/trust machinery — are **not
present in this public repository**. They live in a separate, confidential
product, `swarm_control_pro`, which is private and access-controlled.

This is protection by **absence**, not by obfuscation. Nothing in the public
foundation depends on being secret; an adversary who reads every line of this
repository still gains none of the protected logic, because that logic was
never placed here. The boundary between the public foundation and the private
product is documented in an architectural decision record and enforced
mechanically by an automated release gate that runs on every change, so the
boundary cannot erode over time.

## How the intellectual property is protected — layered

The company protects its IP through several reinforcing layers:

1. **Proprietary licensing.** This foundation is released under a limited-use
   proprietary license; the confidential product is not licensed for
   distribution at all. Contribution terms ensure that material submitted to
   this repository grants the company the rights it needs, and explicitly
   provide that collaboration does not create any employment, compensation, or
   payment obligation.
2. **A confidential product tier.** The proprietary innovations are held in a
   private repository, disclosed only to parties under written confidentiality
   obligations, on a need-to-know basis.
3. **Access governance.** Access to the confidential tier is controlled,
   audited, and least-privilege. The public foundation and the confidential
   product are kept in separate repositories under separate access policies.
4. **Trade-secret practice.** The confidential material is maintained as trade
   secrets under reasonable protective measures, including access control,
   confidentiality obligations, and the architectural boundary described
   above.
5. **Copyright and trademark.** All original material is protected by
   copyright and released only under the stated license; the company's marks
   are reserved.
6. **Protected engineering process.** Both repositories use protected release
   branches with required review and automated checks, a committed-secret
   scanning gate, and a security posture documented under `DOCS/SECURITY.md`.

## What an investor should take away

- The public foundation is a **showcase and a substrate**, engineered to
  demonstrate quality and capability while carrying **none** of the
  value-bearing intellectual property.
- The defensible IP is protected by construction: it is separated into a
  confidential product, access-controlled, held as trade secrets, and shielded
  by a boundary that is enforced in software, not merely by policy.
- The protection strategy is layered — licensing, confidentiality, access
  governance, trade-secret practice, and copyright/trademark — so that no
  single point of failure exposes the company's IP.

A confidential companion document, maintained in the private product
repository, describes the protected intellectual property and its safeguards
in the detail appropriate for diligence under a non-disclosure agreement.

## Contact

Licensing, collaboration, diligence, and IP inquiries:
`emilio@vitruvian.systems`

---

*This document describes the company's IP-protection posture for information
purposes. It is not legal advice and not a license; the [LICENSE](./LICENSE)
governs use of this software.*
