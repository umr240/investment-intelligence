# Mental Models — Canonical Index

> Generated reference for the latticework. Maintained by hand; will be auto-generated when the composer ships at Phase 6.1. See `README.md` for schema, `_gaps.md` for sparse domains and candidates.

## Inventory: 114 models

### `core/` — always-loaded foundation (12)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`owner_operator_stance`](core/owner_operator_stance.md) | Owner-Operator Stance | buffett | ◯ |
| [`inversion`](core/inversion.md) | Inversion | munger | ◯ |
| [`circle_of_competence`](core/circle_of_competence.md) | Circle of Competence | buffett | ◯ |
| [`first_principles`](core/first_principles.md) | First Principles | aristotle / feynman | ◯ |
| [`margin_of_safety`](core/margin_of_safety.md) | Margin of Safety | graham / buffett | ◯ |
| [`second_order_thinking`](core/second_order_thinking.md) | Second-Order Thinking | marks | ◯ |
| [`opportunity_cost`](core/opportunity_cost.md) | Opportunity Cost | economics | ◯ |
| [`probabilistic_thinking`](core/probabilistic_thinking.md) | Probabilistic Thinking | tetlock / kahneman | ◯ |
| [`compounding`](core/compounding.md) | Compounding | buffett / munger | ◯ |
| [`lollapalooza`](core/lollapalooza.md) | Lollapalooza | munger | ◯ |
| [`incentive_structures`](core/incentive_structures.md) | Incentive Structures | munger | ◯ |
| [`buffett_ten_year_hold`](core/buffett_ten_year_hold.md) | Buffett's 10-Year-Hold Test | buffett | ◯ |

### `moat/` — loaded when company has revenue (6)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`munger_dorsey_five_sources`](moat/munger_dorsey_five_sources.md) | Five Structural Sources of Moat | munger / dorsey | ◯ |
| [`helmer_seven_powers`](moat/helmer_seven_powers.md) | Helmer's 7 Powers | helmer | ★★ |
| [`moat_direction`](moat/moat_direction.md) | Moat Direction (Derivative Beats Level) | practitioner | ◯ |
| [`tam_ceiling`](moat/tam_ceiling.md) | TAM Ceiling | practitioner | ◯ |
| [`lunch_eating_test`](moat/lunch_eating_test.md) | The Lunch-Eating Test | practitioner | ◯ |
| [`challenger_inversion_test`](moat/challenger_inversion_test.md) | $1B-Funded-Challenger Inversion Test | practitioner | ◯ |

### `management/` — loaded when DEF 14A / proxy data present (1)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`thorndike_outsiders_eight_traits`](management/thorndike_outsiders_eight_traits.md) | Thorndike Outsiders 8 Traits | thorndike | ◯ |

### `bias/` — always-loaded guardrails (12)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`confirmation_bias`](bias/confirmation_bias.md) | Confirmation Bias | kahneman / munger | ★★ |
| [`authority_bias`](bias/authority_bias.md) | Authority Bias | cialdini / munger | ★★ |
| [`recency_bias`](bias/recency_bias.md) | Recency Bias | kahneman | ★★ |
| [`anchoring_bias`](bias/anchoring_bias.md) | Anchoring Bias | kahneman | ★★ |
| [`sunk_cost`](bias/sunk_cost.md) | Sunk Cost Bias | kahneman | ★★ |
| [`liking_loving_tendency`](bias/liking_loving_tendency.md) | Liking / Loving Tendency | munger | ◯ |
| [`motivated_reasoning_fire`](bias/motivated_reasoning_fire.md) | Motivated Reasoning (FIRE-Goal Specific) | munger | ◯ |
| [`prospect_theory_loss_aversion`](bias/prospect_theory_loss_aversion.md) | Prospect Theory & Loss Aversion | kahneman / tversky | ★★★ |
| [`availability_heuristic`](bias/availability_heuristic.md) | Availability Heuristic | kahneman / tversky | ★★★ |
| [`narrative_fallacy`](bias/narrative_fallacy.md) | Narrative Fallacy | taleb | ★★ |
| [`social_proof`](bias/social_proof.md) | Social Proof | cialdini | ★★ |
| [`commitment_consistency`](bias/commitment_consistency.md) | Commitment & Consistency | cialdini | ★★ |

### `statistical/` — quantitative reasoning (5)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`regression_to_mean`](statistical/regression_to_mean.md) | Regression to the Mean | galton / kahneman | ★★★ |
| [`base_rate_fallacy`](statistical/base_rate_fallacy.md) | Base Rate Fallacy | kahneman / tversky | ★★★ |
| [`survivorship_bias`](statistical/survivorship_bias.md) | Survivorship Bias | standard | ★★★ |
| [`bayesian_updating`](statistical/bayesian_updating.md) | Bayesian Updating | bayes / jaynes | ★★★ |
| [`sample_size_law_of_small_numbers`](statistical/sample_size_law_of_small_numbers.md) | Law of Small Numbers | kahneman / tversky | ★★★ |

### `engineering/` — engineering principles (34)

Largest single domain — split into four functional groupings for browsability.

#### Reliability / SRE (6)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`failure_mode_analysis`](engineering/failure_mode_analysis.md) | Failure Mode Analysis | reliability engineering | ★★ |
| [`redundancy`](engineering/redundancy.md) | Redundancy (Belt-and-Braces) | reliability engineering | ★★ |
| [`blast_radius`](engineering/blast_radius.md) | Blast Radius | SRE / security | ★★ |
| [`defense_in_depth`](engineering/defense_in_depth.md) | Defence in Depth | security / reliability | ★★ |
| [`failure_pareto`](engineering/failure_pareto.md) | Failure Pareto (80/20) | reliability engineering | ★★ |
| [`root_cause_over_symptom`](engineering/root_cause_over_symptom.md) | Root Cause over Symptom (Five Whys) | ohno / toyota | ★★ |

#### Software engineering — foundational ★★★ (10)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`fail_fast`](engineering/fail_fast.md) | Fail Fast | erlang / armstrong | ★★★ |
| [`illegal_states_unrepresentable`](engineering/illegal_states_unrepresentable.md) | Make Illegal States Unrepresentable | minsky / ocaml | ★★★ |
| [`parse_dont_validate`](engineering/parse_dont_validate.md) | Parse, Don't Validate | alexis king | ★★★ |
| [`yagni`](engineering/yagni.md) | YAGNI | kent beck / xp | ★★★ |
| [`single_source_of_truth`](engineering/single_source_of_truth.md) | Single Source of Truth | standard | ★★★ |
| [`idempotency`](engineering/idempotency.md) | Idempotency | helland / distributed systems | ★★★ |
| [`boundaries_hexagonal`](engineering/boundaries_hexagonal.md) | Boundaries / Hexagonal Architecture | cockburn | ★★★ |
| [`functional_core_imperative_shell`](engineering/functional_core_imperative_shell.md) | Functional Core, Imperative Shell | gary bernhardt | ★★★ |
| [`chestertons_fence`](engineering/chestertons_fence.md) | Chesterton's Fence | chesterton | ★★★ |
| [`two_hard_things`](engineering/two_hard_things.md) | Two Hard Things | karlton | ★★★ |

#### Software engineering — practical ★★ (8)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`boring_technology`](engineering/boring_technology.md) | Boring Technology | dan mckinley | ★★ |
| [`composition_over_inheritance`](engineering/composition_over_inheritance.md) | Composition over Inheritance | gof | ★★ |
| [`rule_of_three`](engineering/rule_of_three.md) | Rule of Three | xp | ★★ |
| [`code_read_more_than_written`](engineering/code_read_more_than_written.md) | Code is Read More than Written | standard | ★★ |
| [`test_failure_modes_not_happy_paths`](engineering/test_failure_modes_not_happy_paths.md) | Test the Failure Modes, Not Happy Paths | standard | ★★ |
| [`test_behaviour_not_implementation`](engineering/test_behaviour_not_implementation.md) | Test Behaviour, Not Implementation | standard | ★★ |
| [`pre_mortem_before_commit`](engineering/pre_mortem_before_commit.md) | Pre-Mortem Before Commit | klein / standard | ★★ |
| [`tracer_bullets`](engineering/tracer_bullets.md) | Tracer Bullets | pragmatic programmer | ★★ |

#### Software engineering — contested heuristics ◯ (3)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`dry_caveat`](engineering/dry_caveat.md) | DRY — With Caveats | pragmatic programmer | ◯ |
| [`premature_optimisation_caveat`](engineering/premature_optimisation_caveat.md) | "Premature Optimisation" — With Caveats | knuth | ◯ |
| [`boy_scout_rule_caveat`](engineering/boy_scout_rule_caveat.md) | Boy Scout Rule — With Caveats | martin | ◯ |

#### Claude Code / AI agent discipline (7)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`read_before_writing`](engineering/read_before_writing.md) | Read Before Writing | agent engineering | ★★★ |
| [`mirror_existing_patterns`](engineering/mirror_existing_patterns.md) | Mirror Existing Patterns | agent engineering | ★★★ |
| [`respect_the_contract`](engineering/respect_the_contract.md) | Respect the Contract | agent engineering | ★★★ |
| [`verify_with_tests`](engineering/verify_with_tests.md) | Verify With Tests, Not Assertions | agent engineering | ★★★ |
| [`when_uncertain_ask`](engineering/when_uncertain_ask.md) | When Uncertain, Ask | agent engineering | ★★★ |
| [`one_concern_per_change`](engineering/one_concern_per_change.md) | One Concern Per Change | agent engineering | ★★★ |
| [`failing_test_before_fix`](engineering/failing_test_before_fix.md) | Failing Test Before Fix | agent engineering | ★★★ |

### `systems/` — systems thinking (5)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`feedback_loops`](systems/feedback_loops.md) | Feedback Loops (Reinforcing vs Balancing) | senge / meadows | ★★ |
| [`stocks_vs_flows`](systems/stocks_vs_flows.md) | Stocks vs Flows | forrester / meadows | ★★ |
| [`leverage_points`](systems/leverage_points.md) | Leverage Points (Meadows) | meadows | ★★ |
| [`unintended_consequences`](systems/unintended_consequences.md) | Law of Unintended Consequences | merton | ★★ |
| [`bottleneck_theory_of_constraints`](systems/bottleneck_theory_of_constraints.md) | Theory of Constraints (Bottlenecks) | goldratt | ★★ |

### `biology/` — antifragility & evolution (5)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`antifragility`](biology/antifragility.md) | Antifragility | taleb | ★★ |
| [`selection_pressure`](biology/selection_pressure.md) | Selection Pressure | darwin / dawkins | ★★★ |
| [`evolutionary_stable_strategies`](biology/evolutionary_stable_strategies.md) | Evolutionary Stable Strategies (ESS) | maynard smith | ★★★ |
| [`hormesis`](biology/hormesis.md) | Hormesis (Stressors Strengthen) | selye / taleb | ★ |
| [`red_queen_effect`](biology/red_queen_effect.md) | Red Queen Effect | van valen | ★★ |

### `game_theory/` — strategic interaction (5)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`nash_equilibrium`](game_theory/nash_equilibrium.md) | Nash Equilibrium | nash | ★★★ |
| [`signalling_games`](game_theory/signalling_games.md) | Signalling Games (Spence) | spence | ★★★ |
| [`repeated_games`](game_theory/repeated_games.md) | Repeated Games (Axelrod) | axelrod | ★★★ |
| [`commitment_devices`](game_theory/commitment_devices.md) | Commitment Devices (Schelling) | schelling | ★★★ |
| [`prisoners_dilemma_industries`](game_theory/prisoners_dilemma_industries.md) | Prisoners' Dilemma Industries | standard | ★★ |

### `physics/` — physical-system analogies (5)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`entropy`](physics/entropy.md) | Entropy (Moats Decay) | thermodynamics | ★★ |
| [`equilibrium_vs_steady_state`](physics/equilibrium_vs_steady_state.md) | Equilibrium vs Steady State | standard | ★★ |
| [`critical_mass`](physics/critical_mass.md) | Critical Mass | standard | ★★ |
| [`leverage_archimedes`](physics/leverage_archimedes.md) | Leverage (Archimedes / Buffett) | archimedes / buffett | ★★ |
| [`phase_transitions`](physics/phase_transitions.md) | Phase Transitions | statistical mechanics | ★★ |

### `history/` — cycles and analogs (5)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`four_seasons_dalio`](history/four_seasons_dalio.md) | Four Seasons (Dalio) | dalio | ★★ |
| [`pattern_matching_wrong_analog`](history/pattern_matching_wrong_analog.md) | Pattern Matching to the Wrong Analog | standard | ★★ |
| [`historical_base_rates`](history/historical_base_rates.md) | Historical Base Rates | standard | ★★★ |
| [`kondratieff_long_waves`](history/kondratieff_long_waves.md) | Kondratieff Long Waves | kondratieff / schumpeter | ★ |
| [`mean_reversion_secular_vs_cyclical`](history/mean_reversion_secular_vs_cyclical.md) | Mean Reversion — Secular vs Cyclical | standard | ★★ |

### `epistemology/` — knowledge-discipline (4)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`confidence_calibration`](epistemology/confidence_calibration.md) | Confidence Calibration | tetlock | ★★★ |
| [`intersubjective_verification`](epistemology/intersubjective_verification.md) | Intersubjective Verification | popper | ★★ |
| [`falsifiability`](epistemology/falsifiability.md) | Falsifiability | popper | ★★★ |
| [`epistemic_humility_unknown_unknowns`](epistemology/epistemic_humility_unknown_unknowns.md) | Epistemic Humility (Unknown Unknowns) | rumsfeld / standard | ★★ |

### `information_theory/` — signal extraction (4)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`signal_vs_noise`](information_theory/signal_vs_noise.md) | Signal vs Noise | shannon | ★★★ |
| [`kelly_criterion`](information_theory/kelly_criterion.md) | Kelly Criterion | kelly / thorp | ★★★ |
| [`efficient_market_filtration`](information_theory/efficient_market_filtration.md) | Efficient Market Filtration | fama / asness | ★★★ |
| [`channel_capacity`](information_theory/channel_capacity.md) | Channel Capacity | shannon | ★★★ |

### `valuation/` — overlay-conditional (3)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`intangible_capital_peters_taylor`](valuation/intangible_capital_peters_taylor.md) | Intangible Capital (Peters-Taylor) | peters / taylor | ★★★ |
| [`eisfeldt_papanikolaou_org_capital`](valuation/eisfeldt_papanikolaou_org_capital.md) | Eisfeldt-Papanikolaou Organisation Capital | eisfeldt / papanikolaou | ★★★ |
| [`bessembinder_extreme_winners`](valuation/bessembinder_extreme_winners.md) | Bessembinder Extreme Winners | bessembinder | ★★★ |

### `lifecycle/` — stage-conditional (4)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`pre_discovery_archetype`](lifecycle/pre_discovery_archetype.md) | Pre-Discovery Archetype (F1 Profile) | lifecycle | ★★ |
| [`platform_dominator_archetype`](lifecycle/platform_dominator_archetype.md) | Platform Dominator Archetype (F6 Profile) | lifecycle | ★★ |
| [`post_spinoff_archetype`](lifecycle/post_spinoff_archetype.md) | Post-Spinoff Archetype (PSA Overlay) | cusatis / desai-jain | ★★★ |
| [`recent_ipo_caution`](lifecycle/recent_ipo_caution.md) | Recent-IPO Caution | practitioner | ★★ |

### `meta/` — models about models (4)

| Slug | Name | School | Tier |
|---|---|---|---|
| [`lollapalooza_alignment_detector`](meta/lollapalooza_alignment_detector.md) | Lollapalooza Alignment Detector | munger meta | ◯ |
| [`man_with_hammer_warning`](meta/man_with_hammer_warning.md) | Man with a Hammer Warning | munger meta | ◯ |
| [`taxonomy_of_uncertainty`](meta/taxonomy_of_uncertainty.md) | Taxonomy of Uncertainty | knight / keynes | ★★★ |
| [`model_retirement_criteria`](meta/model_retirement_criteria.md) | Model Retirement Criteria | adr-024 | ★★ |

## Coverage by tier

| Tier | Count | Notes |
|---|---|---|
| ★★★ peer-reviewed academic / strong empirical / agent-discipline | 46 | Foundational SE principles, statistical thinking, game theory, info theory, agent discipline, valuation methodology, post-spinoff alpha, taxonomy of uncertainty |
| ★★ strong empirical / industry-validated | 49 | Helmer, engineering reliability, systems, physics, history, biology, practical SE, lifecycle archetypes, model retirement criteria |
| ★ heuristic with practitioner consensus | 2 | Hormesis, Kondratieff long waves |
| ◯ qualitative lens / contested heuristic | 17 | Munger lattice, moat refinements, Outsiders, owner-operator stance, contested SE rules, meta-level lattice models |

## Coverage by school (count of models touching each school)

| School | Count |
|---|---|
| Munger | 8 |
| Buffett | 4 |
| Kahneman / Tversky | 8 |
| Taleb | 4 |
| Cialdini | 3 |
| Helmer / Thorndike / Graham / Marks / Dorsey | 5 |
| Practitioner / Standard | ~22 (across moat refinements, history, software-engineering, etc.) |
| Reliability engineering | 5 |
| Systems thinkers (Senge, Meadows, Forrester, Goldratt, Merton) | 5 |
| Game theorists (Nash, Spence, Axelrod, Schelling, Maynard Smith) | 6 |
| Information theory (Shannon, Kelly, Fama) | 4 |
| Epistemology (Popper, Tetlock, Rumsfeld) | 4 |
| Physics / thermodynamics | 5 |
| History / macro (Dalio, Kondratieff) | 2 |
| Biology (Darwin, Van Valen, Selye) | 3 |
| Software engineering (Beck/Martin/McKinley/Bernhardt/Cockburn/Karlton/King/Knuth/Erlang/Chesterton/GoF/Pragmatic/Helland/Ohno) | 22 |
| Agent engineering (Claude-Code-specific) | 7 |

## Maintenance

- **Adding a model**: write the file, add a row above, remove the corresponding row in `_gaps.md` (if listed), update CLAUDE.md only if the model belongs in the stance summary
- **Retiring a model**: delete the file, remove the row above, log under "Retired models" in `_gaps.md`
- **Annual review**: any model with `last_reviewed` >12 months old surfaces here for retire-or-update decision (Phase 6.1+ — when tooling exists, this becomes auto-generated)

## Path forward (post-111)

Initial target was 100; Stage C extension closed `valuation/` (3) + `lifecycle/` (4) + `meta/` (4) for an inventory of 111 across **all 16 directories populated**. Future growth runs through:

- **Refinements within dense areas** — selective additions where they strengthen specific decisions (volatility drag, fractional Kelly, Simpson's paradox, BIC, chaos engineering, mechanism design — see `_gaps.md` candidates)
- **`mental_model_composer.py`** — runtime selector + token budget enforcement (Phase 6.1 — when `narrative.py` ships)
- **Auto-generated `_index.md`** from frontmatter — replace this hand-maintained file with generated artifact
- **Bidirectional `related_models` link validator** — graph-integrity check at CI
- **Annual pruning (begins 2027-05)** — `last_reviewed` >12 months → retire-or-update; quality dominates count
- **Per-model regression tests** — assert each model's contribution to specific narrative outputs (requires `narrative.py`)
