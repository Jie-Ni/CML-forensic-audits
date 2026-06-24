# W08 TIFS 90-Point Threat Model And Decision Protocol

Date: 2026-06-23

This document defines the target TIFS-grade paper, not the evidence currently
available in the manuscript. A claim may move from this protocol into the main text
only after the corresponding hard-bar gate passes.

## Parties

- **Teacher owner.** Owns or controls a candidate reasoning model and can authorize
  likelihood scoring under that model. The owner may not know the suspect's weights,
  training data, or service internals.
- **Suspect deployer.** Serves a model through output-only access. The suspect may
  have been trained from teacher traces, independently trained, or adaptively
  laundered to hide teacher descent.
- **Verifier.** Collects suspect outputs on an audit problem pool, generates a
  same-base reference when the suspect base is known or declared, scores suspect and
  reference traces under candidate teachers, calibrates thresholds on controls, and
  reports detection, attribution, or abstention.

## Access Tiers

- **T0: suspect output only.** The verifier receives natural-language traces from
  the suspect. No suspect logits, weights, gradients, hidden states, training logs, or
  private datasets are assumed.
- **T1: candidate scoring.** Candidate teachers provide authorized likelihood scores
  for the audit traces. This can be owner-side scoring, escrowed scoring, or a
  reproducible local model checkpoint.
- **T2: reference generation.** The verifier can generate same-base non-distilled
  reference traces. If the base is unknown or not runnable, the protocol must either
  abstain or enter an explicitly measured no-reference fallback condition.
- **T3: review reproduction.** A reviewer can rebuild summary statistics from staged
  raw traces, model/adapter revisions, scored matrices, run logs, and an environment
  lock. Figure-source regeneration alone is not enough for 90-point claims.

## Attacker Knowledge

The 90-point package must report results under at least three knowledge levels:

- **Naive distillation.** The suspect trains on teacher traces and does not know the
  detector.
- **Protocol-aware laundering.** The suspect knows that likelihood-based CML/MTCR
  scoring is used and perturbs output traces after distillation.
- **Reference-aware laundering.** The suspect knows the broad same-base reference
  assumption and tries to move traces toward an independently trained same-base style.

## Required Attack Surface

The hard-bar package must measure, at minimum:

- identity control;
- second-model paraphrase laundering;
- answer-only distillation;
- chain-of-thought compression or truncation;
- style rewriting with a non-candidate LLM;
- decoding perturbation across temperature/top-p;
- mixed human-and-teacher training traces at multiple dilution levels;
- selective training on low-score or low-suspicion traces.

Each attack must report AUROC, TPR at 1 percent FPR, FPR at the zero threshold,
student-level confidence intervals, threshold source, and exact attack recipe.

## Open-Set And False-Accusation Policy

The verifier must not force a closed-set teacher label when the source teacher is
absent from the candidate set. The 90-point decision protocol has three outputs:

- **Detect.** Evidence supports distillation from the declared candidate set.
- **Attribute.** Evidence supports a specific teacher within the declared candidate
  set after passing closed-set and open-set checks.
- **Abstain.** Candidate evidence is insufficient, the source teacher is plausibly
  absent, the base/reference is missing, or sibling teachers are not separable at the
  calibrated threshold.

The open-set evaluation must include source-present closed-set controls, source
teacher absent, sibling teacher absent, unrelated capable teacher present, and public
model decoy conditions. It must report coverage, abstention rate, and false
attribution rate, not just accuracy among non-abstained cases.

## Generalization Matrix

The paper is not TIFS-90 unless the tested grid includes:

- at least one non-Qwen student base, preferably Llama-3.1-8B or Mistral-7B;
- same-family, cross-family, and shared-ancestor teacher relations;
- math reasoning (GSM8K/MATH), non-math reasoning (BBH or ARC-Challenge), and code
  reasoning (MBPP or HumanEval);
- held-out controls for threshold calibration and FPR reporting.

## Baseline Policy

The baseline table must compare CML and CML+MTCR against:

- base-relative likelihood surplus;
- a Wadhwa-style closed-set teacher classifier;
- Model Provenance Testing style multiple-hypothesis testing;
- embedding/MMD behavioral similarity;
- a style classifier;
- a simple perplexity/log-probability baseline.

All baselines must use the same calibration split and report TPR at 1 percent FPR,
FPR0, AUROC, and confidence intervals. White-box baselines may be reported as access
upper bounds, but must not be treated as same-access comparisons.

## Statistical Unit

The independent unit is the trained student, not an individual trace. Main claims
need at least five independently trained students per key cell. Trace-level curves
can show operating resolution, but they cannot replace student-level confidence
intervals or held-out FPR.

## Reproducibility Gate

A 90-point reviewer package must include:

- raw suspect/reference/candidate trace manifests and hashes;
- model revisions and tokenizer revisions;
- student adapter or checkpoint hashes, or escrow IDs with validation status;
- scored matrices for every main and supplementary claim;
- run logs with command hashes, stdout/stderr hashes, node/GPU/CUDA/environment
  metadata, stage-in and stage-out paths;
- scripts that rebuild tables and figures from staged artifacts;
- an environment lock;
- an anonymized archive or DOI when allowed by PI and venue policy.

Until this gate passes, the manuscript must describe the current package as
figure-source reproducible only, not end-to-end experiment reproducible.
