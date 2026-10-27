# Briefing evaluation report

- Date (UTC): 2026-10-27
- Provider: groq
- Model: openai/gpt-oss-20b
- Prompt version: v1

Scenarios: 28 | Raw briefings: 28 | Validator-corrected briefings: 28

| Check | Raw pass rate | Final pass rate |
| --- | ---: | ---: |
| route_matches_engine | 28/28 (100.0%) | 28/28 (100.0%) |
| severe_coverage | 25/28 (89.3%) | 28/28 (100.0%) |
| no_risk_downgrade | 28/28 (100.0%) | 28/28 (100.0%) |
| no_false_safe | 0/28 (0.0%) | 28/28 (100.0%) |
| numbers_grounded | 11/28 (39.3%) | 28/28 (100.0%) |
| route_ids_grounded | 18/28 (64.3%) | 28/28 (100.0%) |
| place_names_grounded | 19/28 (67.9%) | 28/28 (100.0%) |

## Pass rates by scenario category

| Category | Scenarios | Check | Raw pass rate | Final pass rate |
| --- | ---: | --- | ---: | ---: |
| normal | 8 | route_matches_engine | 100.0% (8/8) | 100.0% (8/8) |
| normal | 8 | severe_coverage | 100.0% (8/8) | 100.0% (8/8) |
| normal | 8 | no_risk_downgrade | 100.0% (8/8) | 100.0% (8/8) |
| normal | 8 | no_false_safe | 0.0% (0/8) | 100.0% (8/8) |
| normal | 8 | numbers_grounded | 37.5% (3/8) | 100.0% (8/8) |
| normal | 8 | route_ids_grounded | 87.5% (7/8) | 100.0% (8/8) |
| normal | 8 | place_names_grounded | 62.5% (5/8) | 100.0% (8/8) |
| severe | 5 | route_matches_engine | 100.0% (5/5) | 100.0% (5/5) |
| severe | 5 | severe_coverage | 60.0% (3/5) | 100.0% (5/5) |
| severe | 5 | no_risk_downgrade | 100.0% (5/5) | 100.0% (5/5) |
| severe | 5 | no_false_safe | 0.0% (0/5) | 100.0% (5/5) |
| severe | 5 | numbers_grounded | 40.0% (2/5) | 100.0% (5/5) |
| severe | 5 | route_ids_grounded | 40.0% (2/5) | 100.0% (5/5) |
| severe | 5 | place_names_grounded | 80.0% (4/5) | 100.0% (5/5) |
| forecast gap | 5 | route_matches_engine | 100.0% (5/5) | 100.0% (5/5) |
| forecast gap | 5 | severe_coverage | 100.0% (5/5) | 100.0% (5/5) |
| forecast gap | 5 | no_risk_downgrade | 100.0% (5/5) | 100.0% (5/5) |
| forecast gap | 5 | no_false_safe | 0.0% (0/5) | 100.0% (5/5) |
| forecast gap | 5 | numbers_grounded | 60.0% (3/5) | 100.0% (5/5) |
| forecast gap | 5 | route_ids_grounded | 0.0% (0/5) | 100.0% (5/5) |
| forecast gap | 5 | place_names_grounded | 60.0% (3/5) | 100.0% (5/5) |
| threshold | 4 | route_matches_engine | 100.0% (4/4) | 100.0% (4/4) |
| threshold | 4 | severe_coverage | 75.0% (3/4) | 100.0% (4/4) |
| threshold | 4 | no_risk_downgrade | 100.0% (4/4) | 100.0% (4/4) |
| threshold | 4 | no_false_safe | 0.0% (0/4) | 100.0% (4/4) |
| threshold | 4 | numbers_grounded | 25.0% (1/4) | 100.0% (4/4) |
| threshold | 4 | route_ids_grounded | 75.0% (3/4) | 100.0% (4/4) |
| threshold | 4 | place_names_grounded | 75.0% (3/4) | 100.0% (4/4) |
| all-risky | 3 | route_matches_engine | 100.0% (3/3) | 100.0% (3/3) |
| all-risky | 3 | severe_coverage | 100.0% (3/3) | 100.0% (3/3) |
| all-risky | 3 | no_risk_downgrade | 100.0% (3/3) | 100.0% (3/3) |
| all-risky | 3 | no_false_safe | 0.0% (0/3) | 100.0% (3/3) |
| all-risky | 3 | numbers_grounded | 33.3% (1/3) | 100.0% (3/3) |
| all-risky | 3 | route_ids_grounded | 100.0% (3/3) | 100.0% (3/3) |
| all-risky | 3 | place_names_grounded | 66.7% (2/3) | 100.0% (3/3) |
| near-tie | 3 | route_matches_engine | 100.0% (3/3) | 100.0% (3/3) |
| near-tie | 3 | severe_coverage | 100.0% (3/3) | 100.0% (3/3) |
| near-tie | 3 | no_risk_downgrade | 100.0% (3/3) | 100.0% (3/3) |
| near-tie | 3 | no_false_safe | 0.0% (0/3) | 100.0% (3/3) |
| near-tie | 3 | numbers_grounded | 33.3% (1/3) | 100.0% (3/3) |
| near-tie | 3 | route_ids_grounded | 100.0% (3/3) | 100.0% (3/3) |
| near-tie | 3 | place_names_grounded | 66.7% (2/3) | 100.0% (3/3) |

## Validator interventions

Fallback template used: 26/28 scenarios.

| Rule | Count |
| --- | ---: |
| add_required_risky_checkpoint | 167 |
| fallback_template | 26 |
| restore_data_gaps | 28 |

## Scenario results

| Scenario | Provider | Raw checks passed | Final checks passed | Interventions | Fallback |
| --- | --- | ---: | ---: | --- | --- |
| all_routes_risky_1_sfo_to_lax | groq | 5/7 | 7/7 | restore_data_gaps, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, fallback_template | yes |
| all_routes_risky_2_denver_to_salt_lake_city | groq | 5/7 | 7/7 | restore_data_gaps, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, fallback_template | yes |
| all_routes_risky_3_boston_to_new_york | groq | 5/7 | 7/7 | restore_data_gaps, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, fallback_template | yes |
| forecast_gap_1_sfo_to_lax | groq | 3/7 | 7/7 | restore_data_gaps, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, fallback_template | yes |
| forecast_gap_2_seattle_to_portland | groq | 5/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| forecast_gap_3_denver_to_salt_lake_city | groq | 4/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| forecast_gap_4_chicago_to_detroit | groq | 4/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| forecast_gap_5_dallas_to_houston | groq | 5/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| near_tie_1_sfo_to_lax | groq | 4/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| near_tie_2_chicago_to_detroit | groq | 5/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| near_tie_3_boston_to_new_york | groq | 6/7 | 7/7 | restore_data_gaps | no |
| normal_atlanta_to_nashville | groq | 5/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| normal_boston_to_new_york | groq | 5/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| normal_chicago_to_detroit | groq | 5/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| normal_dallas_to_houston | groq | 5/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| normal_denver_to_salt_lake_city | groq | 5/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| normal_minneapolis_to_kansas_city | groq | 5/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| normal_seattle_to_portland | groq | 6/7 | 7/7 | restore_data_gaps | no |
| normal_sfo_to_lax | groq | 3/7 | 7/7 | restore_data_gaps, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, fallback_template | yes |
| severe_1_sfo_to_lax | groq | 4/7 | 7/7 | restore_data_gaps, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, add_required_risky_checkpoint, fallback_template | yes |
| severe_2_seattle_to_portland | groq | 5/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| severe_3_denver_to_salt_lake_city | groq | 4/7 | 7/7 | restore_data_gaps, add_required_risky_checkpoint, fallback_template | yes |
| severe_4_chicago_to_detroit | groq | 4/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| severe_5_dallas_to_houston | groq | 4/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| threshold_wind_35_0_load_40000 | groq | 5/7 | 7/7 | restore_data_gaps, add_required_risky_checkpoint, fallback_template | yes |
| threshold_wind_44_9_load_41000 | groq | 4/7 | 7/7 | restore_data_gaps, add_required_risky_checkpoint, fallback_template | yes |
| threshold_wind_45_0_load_30000 | groq | 5/7 | 7/7 | restore_data_gaps, fallback_template | yes |
| threshold_wind_45_0_load_30001 | groq | 4/7 | 7/7 | restore_data_gaps, fallback_template | yes |

## Final-output quality gate

| Check | Final pass rate | Required | Result |
| --- | ---: | ---: | --- |
| route_matches_engine | 100.0% | 100.0% | PASS |
| severe_coverage | 100.0% | 100.0% | PASS |
| no_risk_downgrade | 100.0% | 100.0% | PASS |
| no_false_safe | 100.0% | 100.0% | PASS |
| numbers_grounded | 100.0% | 100.0% | PASS |
| route_ids_grounded | 100.0% | 100.0% | PASS |
| place_names_grounded | 100.0% | 100.0% | PASS |
