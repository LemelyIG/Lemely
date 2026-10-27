# Tutoring marketplace: MUTATION and RED ledger

Extracted from the implementation lanes' return contracts (PLAN.md section 0.6). Branch `feat/tutoring-marketplace`. Nothing below is written from memory: each fenced block is the lane's own RED and MUTATION text, with runs of spaces collapsed and em/en dashes replaced by `-`. Lines identical to an earlier return of the same lane are omitted and counted in a note.

Sources: subagent transcripts of session `6a489433` (W1 to W5 lanes) and session `c4e7dcea` (W6 onward and all fix lanes), under `~/.claude/projects/-home-sico-Code-Lemely--claude-worktrees-tutoring-marketplace/<session>/subagents/`. Section headings are the lane dispatch descriptions. A lane that was resumed has several returns; each is shown. Every SHA token found on a `SHA:` line was checked with `git cat-file -t` and is marked `verified` (all that appear verified; none failed).

Counting rule for the table: a MUTATION block that has indented or bulleted lines under its header counts one per such line; otherwise it counts one. RED lines are not counted in the table, only flagged yes/no. "Test files" are the paths named in the return's ACCEPTANCE line, falling back to its FILES line where noted.

Gaps, stated plainly:
- T16 (copy-lint rule, commit `dc4dea03`, verified): the return is prose only; it has no RED/MUTATION/SHA contract lines, so none are quoted.
- T30 is a security-review lane, not an implementation lane. Its fixes appear as F30-1..F30-6.
- The I0 config hot patch (`858e05c0`, verified) returned prose with no contract lines and is not listed.
- Lanes marked "return not found" below ended on a session-limit notice (F5-17, F5-A, F5-T first dispatches); the same task was re-dispatched in session `c4e7dcea` and appears in its own section.
- Review lanes ("Review Tnn at its SHA") carry no RED/MUTATION lines and are excluded.

## T00 execution tooling
Lane `a12c175c` (6a489433), return 1/1, msg 9/9. SHA: `ab28fce0` verified
```text
RED: test_tutoring_app_helper.py: assert len(flat) >= 150 -> 0 (stub helper) | test_tutoring_affected_tests.py: assert 2 == 0 (affected_tests.py missing) | test_tutoring_tooling.py: assert path.is_file(), 'pytest.sh'
MUTATION (all on <T>, restored -> green):
 pytest.sh accepts zero args -> test_pytest_wrapper_refuses_no_args_directory_and_tests[no-arguments] red
 drop from-a-import-b branch -> test_from_package_import_module_form_detected red
 omit extraPaths -> test_pyright_config_adds_extra_paths_and_absolute_roots red
 static.sh zero-files guard off -> test_static_pyright_step_never_passes_a_run_that_checked_no_files[zero-files,no-stats-line] red
 export paths gain reports -> test_export_command_paths_exclude_reports + test_export_copies_head_overlay_and_links_without_reports red
 gate_db name check off -> test_gate_db_refuses_other_database_names (7 cases) red
 live_e2e lock check off -> test_live_scripts_refuse_without_lock / _a_lock_held_for_another_worktree (8 cases) red
 scan_py minimum off -> test_scan_py_refuses_when_it_finds_fewer_than_the_minimum red
 hubs expanded -> test_hub_change_lists_only_its_pins (+ fixture variant) red
 app_with_routers idempotency off -> test_app_with_routers_mounts_once_and_is_idempotent red
 smoke spec type error -> tsc -p tsconfig.e2e.json red (TS2551)
```
## T01 schema migrations models
Lane `a6b2163c` (6a489433), return 1/2, msg 89/121. SHA: `5d2feb2a` verified
```text
RED (HEAD plus tests only): enums: `assert False` (btree_gist missing) | profiles/outbox/reviews/grants: `assert {'tutor_appro..'} <= {..}` (tables absent) | safety: `'0043_merge_heads' == '0050_tutoring_safety'` | db_schema: `['0043_merge_heads'] == ['0050_tutoring_safety']` | me_router: `assert 'bookingRequest' in {...}`, and the PUT got `extra_forbidden` instead of 200 | prefs_repo: `AssertionError: booking_request` | single_source: `{'lemely/db/m..predicates.py'} <= set()` | migration_tutor_bookings, db_tutoring_schema, tutoring_predicates: n/a (ImportError), so mutations cover them.
MUTATION: listener removed -> test_create_all_on_fresh_database_installs_btree_gist red (`uuid has no default operator class for "gist"`); restored -> green
MUTATION: `IS NOT NULL` conjunct dropped (ORM and 0047) -> test_ck_late_tutor_cancel_requires_reason[create_all,migrated] red (DID NOT RAISE); restored -> green
MUTATION: bookings->profiles FK set to CASCADE (ORM and 0047) -> test_tutor_profile_delete_restricted_when_bookings_exist[*-booking] red; restored -> green
MUTATION: active_block keyed on tutor_profiles.id -> test_active_block_keyed_on_user_ids_not_profile_ids red; restored -> green
MUTATION: one direction dropped -> test_active_block_between_hides_both_directions red; `removed_at IS NULL` dropped -> ..._ignores_removed_rows red; both restored -> green
MUTATION: me.py allows parent_link for student -> test_tutoring_toggle_put_from_disallowed_role_422[student-parent_link] red; restored -> green
MUTATION: a `tutoring_blocks` string added to notification_repo.py -> test_no_module_outside_allowlist_touches_tutoring_blocks red; 'declined' added to the excl predicate -> test_bookings_exclusion_defs_* red; both restored -> green
Mutations ran on c2 (its lemely/, tests/ and SPEC are byte-identical to c3, checked with diff -r) and on an export of the commit.
```
Lane `a6b2163c` (6a489433), return 2/2, msg 121/121. SHA: `c0fd33b6` verified
```text
RED (HEAD plus SPEC and tests only, no implementation): 38 failed. `DID NOT RAISE ValueError` ×28 (unqualified operands); missing `['ck_tutor_profiles_last_initial_len', 'ix_tutoring_admin_access_admin_user_id']`; `AssertionError: tutor_access_audit` (has `updated_at`); `assert None is not None` (admin-log index missing); CHECK set mismatch; `DID NOT RAISE IntegrityError` (empty last initial).
MUTATION (one per fix, each restored to green):
- R2: bare identifiers allowed again → test_block_builders_refuse_unqualified_column_names red (28 cases).
- R3: second operand of student_ever_blocked_tutor_sql left unvalidated → test_block_builders_reject_non_identifier_arguments red on the 7 tutor-position cases.
- R4: `ck_tutor_profiles_bio_len` dropped from 0045 → test_check_cases_cover_every_check_constraint[migrated] red.
- R6: admin_user_id partial index dropped from 0045 → test_admin_access_log_has_partial_admin_user_index[migrated] red.
- NOTE 2: ORM `last_initial_len` CHECK dropped → test_every_check_constraint_rejects_its_violation[last_initial_len-create_all] red.
- NOTE 4: TimestampMixin back on TutorAccessAudit → test_append_only_logs_have_created_at_but_no_updated_at[create_all] red.
- NOTE 7: ix_tutoring_admin_access_tutor renamed in 0045 → test_migration_tutor_profiles::test_constraints_present_by_name red.
- R5 is a test deletion, so it has no mutation.
```
## T02 pure rules A
Lane `afd09837` (6a489433), return 1/2, msg 9/11. SHA: `13e36e9a` verified
```text
RED (each recorded against stub modules that returned neutral values):
- test_core_keyset.py: `assert () == (Decimal('4.166667'), ...)`
- test_core_contact_patterns.py: `assert [] == ['phone']` for "01012345678"
- test_core_tutor_directory.py: `assert {} == {'morning': (360, 720), ...}`
- test_core_tutor_ratings.py: `assert Decimal('4.0') == Decimal('0')` (constants vs SPEC)
MUTATION (all inside the export, restored afterwards, green again):
- Strip digit normalisation -> test_contact_patterns_egyptian_mobile_latin_and_arabic_indic_digits red (13 failed)
- Accept `http:` -> test_meeting_link_allowlist_rejects_userinfo_http_wa_me red (2 failed)
- Remove endpoint tag check -> test_cursor_from_other_endpoint_raises red
- Extra: `review_edit_deadline` on wall clock instead of instant -> test_review_edit_deadline_is_exact_elapsed_time_across_a_clock_change red
- Extra: HOT PATCH contract, with `import sqlalchemy` added to keyset.py in the export -> import-linter BROKEN; restored -> KEPT
```
Lane `afd09837` (6a489433), return 2/2, msg 11/11. SHA: `fcd9d12a` verified; `13e36e9a` verified
```text
RED (tests written first, run on the 13e36e9a code):
- tests/test_core_tutor_directory.py: 27 failed, "DID NOT RAISE InvalidPublicNameError" for the filler, mark-cap and separator-run cases, plus the contact-detail and format-character `student_label` tests.
- tests/test_core_keyset.py: 7 failed (Arabic-Indic and fullwidth decimals, a NUL string, a 257-character string, both datetime overflow cases, int64).
- tests/test_core_contact_patterns.py: 9 failed (7 digit scripts, `https://-.zoom.us/...`, `https://a.-b.zoom.us/...`).
MUTATION (each inside the export, then restored and green; R5 is a docstring plus a pinning test, so it has no mutation):
- R1 filler check off (`if char in _INVISIBLE_LETTERS` -> `if False`) -> test_public_first_name_charset_rejects_digits_urls_bidi red (6 failed)
- R1 mark cap off (`> _MAX_MARKS_PER_LETTER` -> `> 99`) -> same test red (2 failed)
- R1 initial categories widened to include Lm and Mn -> test_public_last_initial_must_be_one_letter red (2 failed)
- R2 separator-run check off -> test_public_first_name_charset_rejects_digits_urls_bidi red (6 failed)
- R3 Decimal regex back to `\d` -> test_cursor_bad_text_for_a_typed_slot_raises red (2 failed)
- R3 int64 bound off -> test_cursor_int_is_bounded_to_int64 red
- R3 string length/NUL guard off -> test_cursor_bad_text_for_a_typed_slot_raises red (2 failed)
- R3 UTC conversion check removed -> test_cursor_bad_text_for_a_typed_slot_raises red (2 failed)
- R4 no digit normalisation -> test_contact_patterns_any_unicode_decimal_digit_script_is_a_digit red (7 failed)
- R6 no contact-detail fallback -> test_student_label_falls_back_when_the_name_carries_contact_details red (6 failed)
- R6 Cf not stripped -> test_student_label_strips_format_characters red
- R8 host labels may start with a hyphen -> test_meeting_link_rejects_lookalike_host_and_port red (2 failed)
```
## T03 booking state machine
Lane `a13958cb` (6a489433), return 1/2, msg 40/65. SHA: `c78e90c8` verified
```text
RED: tests/test_core_booking.py: `assert 'requested' == 'accepted'` (test_target_state_per_action, run against a stub module) | tests/test_core_booking_slots.py: `occurrences(...) == expected` got `[]` (dst_end test). Red run: 25 failed, 7 passed, all failures assertions. The 7 that passed are SPEC-parity guards (n/a, regression guard).
MUTATION: allow student cancel inside 24 h -> test_student_cancel_inside_24h_refused_cancel_window_closed red on T03-c2; restored -> green
MUTATION: drop the round-trip check (`_resolve_wall`, called by occurrences) -> test_dst_start_nonexistent_0030_offers_nothing red; restored -> green
MUTATION: 24 h boundary, three variants (student `<=`→`<`, tutor reason `>`→`>=`, is_late_cancel `>`→`>=`) -> test_cancel_at_exactly_24h_is_not_late red each time (plus the truth-table test for the third); restored -> green
MUTATION (extra): drop the slot-level ambiguity check -> test_repeated_hour_offers_no_slot_and_no_duplicate_label red; restored -> green
```
Lane `a13958cb` (6a489433), return 2/2, msg 65/65. SHA: `01ae544f` verified; `c78e90c8` verified
```text
RED: 18 failed, 34 passed before the code changes. The R7, R4 and R5 tests failed. test_core_booking.py's first failure: `assert isinstance(booking._TARGET_STATE, MappingProxyType)` → False. test_core_booking_slots.py: the six naive-input cases raised TypeError, not the expected ValueError. The R1, R2 and R3 tests passed on the old code, so mutations prove them instead (n/a, regression guard).
MUTATION (all inside c3; after each one I copied the file back from WT and the test was green again):
- R1, `<`→`<=` in `_answer_request`, student/parent cancel of a request, and admin/system cancel (old :356, :366, :376); `>=`→`>` in expire (old :420) → test_transition_guards_flip_exactly_with_the_effective_state red, each failing exactly at STARTS
- R2, `earliest <= slot_start` → `<` → test_slot_exactly_min_notice_ahead_is_offered red
- R3, request treated as live until `ends_at` → probe red on the effective-state assert; `expired` allowed to post in `can_post_note` → probe red on `assert not can_post_note`
- R4, dropped the `action == "expire"` check → test_unknown_action_is_refused red (`'bogus'` → None)
- R5, `_require_aware` made a no-op → all 16 naive-input cases red
- R7, `MappingProxyType` replaced by `dict` → test_target_state_table_is_read_only red
- R6 is a test deletion, so there is nothing to mutate.
```
## T04 API contract DTOs
Lane `afd625b4` (6a489433), return 1/3, msg 71/94. SHA: `79636100` verified
```text
RED: tests/test_schemas_tutoring.py: test_dto_discovery_matches_spec_b3_class_list `assert set() == {...60 SPEC classes}` (docstring-only module skeletons)
RED: web/tests/unit/tutoringTypesParity.test.ts: "expected 0 to be greater than or equal to 77"
MUTATION: tutorUserId on TutorCardDTO -> test_idor_no_public_student_parent_dto_contains_tutor_user_id red; restored -> green
MUTATION: indexable on TutorCardDTO -> test_indexable_only_on_public_card_own_profile_and_admin red; restored -> green
MUTATION: bio on TutorCardDTO -> test_public_dtos_carry_exactly_the_row_5b_fields red; restored -> green
MUTATION: unlisted ExtraCardDTO(PublicTutorCardDTO) -> test_dto_discovery_matches_spec_b3_class_list red; restored -> green
MUTATION: TS TutorCard.headline renamed headLine -> parity "same field names" red; restored -> green
MUTATION (extra): TS Rating.average loses "| null" -> parity type test red; linkedParents on BookingDTO -> parent-link test red; SlotDTO extra=allow -> extra_forbid red; cancel_with_reason dropped -> viewer-action test red; signedUrl on EvidenceDTO -> admin-only-fields test red; email on AdminTutorItemDTO -> email test red; StudentDetailDTO-typed field on ReportDetailDTO -> ADR-T03 test red; AdminEvidenceDTO.signedUrl made str -> O17 test red; all restored -> green
```
Lane `afd625b4` (6a489433), return 2/3, msg 79/94. SHA: `4bb2aa74` verified; `79636100` verified
```text
MUTATION: Python side reverted to `listedSince: str` in the export -> test_every_spec_b3_dto_matches_spec_fields_types_and_defaults red ("TutorProfileDTO.listedSince") and the parity type test red ("string" vs "string | null"); restored -> both green
```
Lane `afd625b4` (6a489433), return 3/3, msg 94/94. SHA: `19055fa3` verified; `79636100` verified; `4bb2aa74` verified
```text
RED: n/a (regression guard) for every new or changed test, each with the mutation below
MUTATION R4: NoteDTO.authorParty gains "parent" -> test_parent_literal_value_only_in_the_three_booking_party_fields red; restored -> green
MUTATION R6: export SPEC §b.3 parenthetical loses `openReports` -> test_admin_tutor_detail_carries_every_own_profile_field red (['openReports']); restored -> green
MUTATION R9a: TutorCardDTO `headline : str` (valid Python the vitest regex skips) and headline removed from TS -> the 5 old parity cases still pass; new vitest count case red ("TutorCardDTO": 6 vs 7) and the new pytest AST test red; restored -> green
MUTATION R9b: AdminTutorDetailDTO `accountEmail : str` and accountEmail removed from TS -> vitest 6/6 still pass; pytest AST test red ("AdminTutorDetailDTO line 111"); restored -> green
```
## T05 grant validity and outcome stats
Lane `ac3a2146` (6a489433), return 1/2, msg 38/72. SHA: `13b54bb0` verified
```text
RED: test_core_tutor_grants.py: test_grant_status_truth_table_with_precedence (None,'never',False,'draft') assert 'active' == 'tutor_unavailable'
RED: test_core_tutor_outcomes.py: test_outcomes_k_counts_n_graded_not_cohort assert 0 == 5 (len(published_members(...)))
RED: test_tutoring_cross_pins.py: test_grant_inputs_cover_python_enums assert not grant_is_valid(revoke_reason='student'); the 4 booking/ORM pins are n/a (regression guard), each with a MUTATION below
MUTATION: k on cohort size (n=len(published)) -> test_outcomes_k_counts_n_graded_not_cohort red on c1; restored -> green
MUTATION: never-granted rule dropped -> test_outcomes_never_granted_between_1_and_k_minus_1_suppresses red (g=1..4); restored -> green
MUTATION: tutor_unavailable checked before revoke_reason -> test_grant_status_truth_table_with_precedence red; restored -> green
MUTATION: 'requested' dropped from excl_tutor_bookings_student_slot where (migration 0047) -> test_active_states_pinned_to_migration_and_orm_where red; restored -> green
MUTATION: ORM late-cancel CHECK '<=' -> '<', and separately '24' -> '12 hours' -> test_cancel_cutoff_pinned_to_late_cancel_check_text red both times; restored -> green
MUTATION: 'system' dropped from booking.Party -> test_core_booking_literals_equal_python_enums red; restored -> green
MUTATION: 'no_show' dropped from the counted states -> test_outcomes_no_show_does_not_remove_member and test_outcome_membership_pinned_to_predicate_index_and_spec red; restored -> green (full acceptance 83 passed after all restores)
MUTATION: HOT PATCH applied in c2 plus `import lemely.db.tutoring_predicates` in tutor_grants -> static.sh import-linter "Tutoring pure rules stay pure" BROKEN; without the forbidden import -> PASS
```
Lane `ac3a2146` (6a489433), return 2/2, msg 72/72. SHA: `d177d0bc` verified
```text
RED: test_core_tutor_outcomes.py: test_late_verification_never_enters_the_published_set[verified-1s-after-S] assert [6, 1, 2, 3, 4] == [1, 2, 3, 4, 5]; the 48-row truth table, row verified at S+1s: assert True is False; test_naive_start_on_an_ineligible_member_refused[no-hold, behind-the-hold] DID NOT RAISE
RED: test_core_tutor_grants.py: test_grant_expiry_in_the_repeated_hour assert 'active' == 'expired'
RED: R2 and R3 tests pass on the old code: n/a (regression guard), each with a mutation below
MUTATION: R1 verification test reduced to "email_verified_at is not None" -> test_late_verification_never_enters_the_published_set red; restored -> green
MUTATION: R2 key=lambda m: m.ref -> test_published_order_is_close_instant_then_ref red ([3, 12, 44, 57, 91] != [57, 91, 3, 44, 12]); restored -> green
MUTATION: R3 change figure gets never_granted=graded_never_granted -> test_never_granted_is_counted_per_figure red (4 of 4); restored -> green
MUTATION: R4 per-member start check removed -> test_naive_start_on_an_ineligible_member_refused red (2 of 2); restored -> green
MUTATION: extra: grant expiry compared without UTC -> test_grant_expiry_in_the_repeated_hour red; is_counted_session without UTC -> test_instants_in_the_repeated_hour_compare_as_instants red; both restored -> green
```
## T06 profiles directory route classes
Lane `ad8445ef` (6a489433), return 1/2, msg 57/77. SHA: `cdc25ad2` verified
```text
RED:
- test_tutoring_http.py: `assert None == 'private, no-store'`
- test_tutor_directory_repo.py: `assert [] == [UUID(...), ...]` (the sort test)
- test_tutor_profile_repo.py: `DID NOT RAISE NotATeacherError`
- test_web_tutoring_public.py: `assert 404 == 200`
- test_web_tutor.py: `assert 404 == 201`
- test_web_tutoring_authz_profiles.py: `assert 0 == 5` (O1 route count)
MUTATION:
- Block anti-join dropped → test_block_anti_join_hides_blocked_tutor_for_student red on c3; restored → green (plus the O11 route test).
- P2 predicate made `listing_state='listed'` (paused served) → test_p2_404_identical_…[paused] red (`200 == 404`); restored → green.
- `indexable` edit re-enters review → the repo and route `test_indexable_change_does_not_send_profile_back_to_review` both red; restored → green.
- TutoringRoute returns handled exceptions without headers (2xx only) → test_tutoring_route_sets_no_store_… red on all 5 non-2xx cases, the 2 2xx cases green; restored → 7 green.
- `bio` added to P1 items → test_p1_p2_p3_json_keys_within_row_5b_allowlist red (`('P1', ['bio'])`); restored → green.
- (extra, §i.4) minRating rounded to 2 decimals → test_min_rating_excludes_new_tutors and test_min_rating_filter_matches_card_rounding red; restored → green.
```
Lane `ad8445ef` (6a489433), return 2/2, msg 77/77. SHA: `cec1c00d` verified; `cdc25ad2` verified
No RED or MUTATION lines in this return.
## T07 notifications email outbox
Lane `a17a7ddf` (6a489433), return 1/2, msg 5/9. SHA: `685b3578` verified
```text
RED (each against a stub module, so the failures are assertions or `NotImplementedError`, not import errors):
- test_notify_email.py: 58 failed, first at `assert set(EMAIL_TEMPLATES) == named`
- test_email_outbox_repo.py and test_tutoring_email.py: 25 failed (e.g. `assert 'mock' in 'stub'`)
- test_tutoring_notify.py and test_scheduled_notifications.py: 41 failed
- notificationPrefs, notifications and staffInbox tests: 17 failed (`visibleToggles is not a function`, key lists differ)
MUTATION (run inside the export, restored afterwards, green again):
- Note text in a notice body: `test_notify_note_notification_has_no_body_text` red (`{'text'}` in the signature).
- Mock rows marked `sent`: `test_email_mock_marks_skipped_not_sent` red.
- Address scrub removed: `test_email_last_error_has_no_address` and `test_failed_row_never_retried` red (3 failed).
- Null tutoring toggle rendered: 4 `visibleToggles` tests red.
```
Lane `a17a7ddf` (6a489433), return 2/2, msg 9/9. SHA: `52fc3f31` verified; `685b3578` verified
```text
RED: 15 failed before the fixes, all assertion or `TypeError` failures, e.g. `'mock_provider' == 'preference_off'`, `review_notices() got an unexpected keyword argument 'revision'`, `assert True is False` (the cap lock was free).
MUTATION (each run inside the export, then restored and green):
- R2, send-time preference check disabled: the two `preference` tests in `test_tutoring_email.py` go red (2 failed).
- R3, cap lock removed: `test_daily_cap_is_not_overshot_by_concurrent_workers` and `test_deliver_job_claims_with_skip_locked_across_two_workers` go red (2 failed).
- R5, revision dropped from the dedupe key: `test_re_moderating_an_edited_review_to_the_same_outcome_sends_a_second_notice`, `test_review_text_moderation_notice_goes_to_the_author_with_the_review_id` and `test_dedupe_keys_match_spec_table` go red (3 failed). The last one parses the SPEC table.
- R6, `allowed_audiences` removed from `BookingAccepted`: `test_accepted_and_declined_are_never_addressed_to_the_tutor` goes red.
- R9, `attempts` always 1: the mock, unverified and `preference_off` tests go red (3 failed).
- R8, hermetic tests: with `LEMELY_EMAIL__API_KEY=x` exported, the old tests failed (3 failed). After the fix both run clean with and without the variable.
```
## T08 edge indexing and cache
Lane `af59f7f7` (6a489433), return 1/2, msg 57/74. SHA: `3d686eaa` verified
```text
RED: workerTutorRobots.test.ts: "serves the SPA shell for /tutors" failed with "expected 599 to be 200" (the request was proxied to the backend); 10 of 13 failed. The 3 that passed before code are the non-vacuity case and the two /api/* regression guards (M6, M7).
RED: test_deploy_headers.py::test_nginx_index_html_sets_x_robots_tag_for_tutors failed with "web/nginx.conf needs one `map $request_uri $robots_tag` block"; ::test_wrangler_… failed with "['/api/*'] == ['/api/*', '/tutors', '/tutors/*']". The other 3 are regression guards (M4, M5, M10).
RED: headerParity.test.ts and headers.test.ts: n/a (regression guard), covered by M8, M9 and M5.
MUTATION M1 (c1): card branch always omits the header -> opted-out, 404 and fail-closed tests red; restored -> green
MUTATION M2 (c1): inbound cookie forwarded on the lookup -> "carries no cookie…" red; restored -> green
MUTATION M3 (c1): UUID check dropped -> "non-UUID … without calling the backend" red; restored -> green
MUTATION M4 (c2): `Disallow: /tutors` in robots.txt -> test_robots_txt_does_not_disallow_tutors red; restored -> green
MUTATION M5 (c2): `/tutors*` block in _headers -> test_headers_file_has_no_tutors_rule red, plus the headers.test.ts row-17 case; restored -> green
MUTATION M6 (c1): X-Forwarded-Proto removed -> "/api/* proxying is unchanged" red; M7 (c1): every /api/ path made cacheable, or the private guard dropped -> "/api/* other paths are not cached" red; restored -> green
MUTATION M8 (c1): tutor branch skips applySecurityHeaders -> "sets the five security headers…" red and the headerParity helper case red; M9 (c1): a header copy in robots.ts -> headerParity red; M12 (c1): timeout 1000 ms -> fail-closed test red; restored -> green
MUTATION M10, M10b, M11 (c2): CSP removed from /index.html -> repeats_security_headers red; X-Robots-Tag directive removed, or the SPEC-literal regex used -> sets_x_robots_tag red; restored -> green
```
Lane `af59f7f7` (6a489433), return 2/2, msg 74/74. SHA: `b476edc2` verified
```text
RED (`workerTutorRobots.test.ts`, before the fix): R3, R4 and R5 failed on real assertions:
- **R3:** "expected 'sb-access-token=secret' to be null".
- **R4:** "no Cache-Control: expected … called 2 times, but got 1".
- **R5:** "the /api/public response waited for cache.put: expected 'blocked' not to be 'blocked'".
- **R2:** n/a (regression guard). With immutable stubs the existing code already passed, because it copies before editing.
MUTATION (all on c3; each restored with `cp` and green again):
- **R2:** `const page = asset` -> 10 tutor-page and cache tests red with "Can't modify immutable headers."
- **R3:** the public read uses the full proxy request, which forwards the cookie -> "the public read-through forwards no cookie…" red.
- **R4:** `public` requirement dropped -> "stores a public response only when…" red at the "no Cache-Control" case. Set-Cookie check dropped -> the same test red at the "Set-Cookie" case.
- **R5:** `await cache.put(...)` instead of `ctx.waitUntil(...)` -> "stores in the background…" red ("blocked").
- **R6:** `workersRuntime.d.ts` removed -> `tsc -p tsconfig.test.json` fails: Cannot find name `Fetcher`, `ExportedHandler`, `ExecutionContext`; no `default` on `CacheStorage`.
```
## T09 existing routes row 14
Lane `a8b7eb4d` (6a489433), return 1/1, msg 75/75. SHA: `b540af94` verified
```text
RED: test_parent_link_integrity.py: test_unlink_notifies_unlinked_parent_inbox_and_outbox -> outbox [] (assert 0 == 1)
RED: test_class_side_door.py: test_join_school_less_class_of_tutor_notifies_parents[student_join] -> assert [] == [class_joined_tutor rows]
RED: test_email_verified_first_timestamp.py: test_second_verification_keeps_the_first_instant -> 2026-02-14 != 2026-01-05
MUTATION: child-row FOR UPDATE removed -> test_race_two_redeems_at_three_links_exactly_one_succeeds red (2 successes); restored -> green
MUTATION: S17 may delete a school-class enrolment -> test_leave_school_class_404 and test_authz_student_can_leave_school_less_class_only red (204 != 404); restored -> green
MUTATION: unlink event row skipped -> test_unlink_writes_link_event red; restored -> green
MUTATION: mirror overwrites email_verified_at -> second-verification and resend tests red; restored -> green
MUTATION (extra): unlink deletes before locking the child row -> deadlock test red (real Postgres DeadlockDetected); idempotency check after the cap -> relink_at_cap red (409); lock_link without FOR SHARE -> lock test red; notice for school classes -> no_notice[school_class] red; join route guard widened -> test_existing_route_guards_unchanged red. All restored -> green
```
## T09 review fixes
Lane `aafd8aea` (6a489433), return 1/1, msg 18/18. SHA: `95280206` verified; `4f5cebeb` verified; `b540af94` verified
```text
**RED** (before the fix):
- `test_parent_link_integrity.py::test_unlink_does_not_deadlock_with_a_link_holder_inserting_a_row_for_the_child`: `OperationalError(DeadlockDetected … while deleting tuple in "parent_child_links") != True`
- `test_email_verified_first_timestamp.py::test_fake_mirror_second_verification_keeps_the_first_instant`: `assert 2026-02-14 == 2026-01-05`
- `test_class_side_door.py::test_join_by_code_queues_the_class_join_notice`: `assert [] == [2 class_joined_tutor rows]`
- n/a (new API): `test_remove_all_school_less_enrolments_only_that_teachers_school_less`; proved by mutation 5 below.
- n/a (regression guard): the `[]` case, R7's state parametrisation and R3's dependency pins; each proved by the mutations below.
**MUTATION** (each run on the export, red, then restored with `cp` and green again):
1. Unlink back to `with_for_update()`: the deadlock test goes red with DeadlockDetected. Restored: 14 passed.
2. The fake mirror overwrites the timestamp: the fake first-timestamp test goes red. Restored: 4 passed.
3. Adding `require_verified_email` to the `DELETE /student/parent-links` route: `test_existing_route_guards_unchanged` goes red (the set gains `get_user_mirror`, …). Restored: 14 passed.
4. `join_by_code` back to `_enrol_if_absent` with no notice: `test_join_by_code_queues_the_class_join_notice` goes red (`[] == [...]`).
5. `remove_school_less_enrolments_in_session` treats `[]` as all: `test_remove_school_less_enrolments_only_school_less` goes red (`assert 3 == 0`).
6. The notice only goes out for profiles with `first_listed_at`: `test_class_join_notice_in_every_tutor_profile_state` has 5 failed and 3 passed (draft, pending_review, rejected, suspended and closed go red). After restoring 4-6: side-door file 29 passed.
```
## T10 admin approval and evidence
Lane `aaa878e3` (6a489433), return 1/1, msg 40/40. SHA: `9ec27bcc` verified
```text
RED (taken on an export of HEAD + my tests + shape-only stubs of the 5 new modules; the tests were written first but not run before the code):
- test_storage_local.py, test_storage_gcs.py: `TypeError: create_signed_url() got an unexpected keyword argument 'disposition'`
- test_evidence_files.py: `assert 'application/pdf' == 'image/png'`
- test_tutor_approval_repo.py: `NotImplementedError` from the stubbed `approve`. This one is an exception, not an assertion.
- test_tutor_evidence.py: `assert 501 == 201`
- test_web_admin_tutoring.py: `assert 501 == 200`
- test_web_tutoring_authz_admin.py: `assert 501 == 404`
MUTATION (each restored with `cp`; the 155 own tests are green afterwards):
- trust the declared type -> `test_sniffed_type_overrides_declared` and `test_t6_sniffed_type_and_reencode_decide_what_is_stored` red (5 failed)
- skip the access-log insert -> `test_a2_writes_one_evidence_open_row_per_url_and_fails_closed` red (`[] == [rows]`)
- fail open (swallow the insert error in a savepoint) -> same test red (`200 == 500`)
- keep `documents_seen_at` on upload -> `test_documents_seen_cleared_by_upload_delete_and_false_approval` red
- lead ruling, reinstate always to listed -> `test_reinstate_never_approved_returns_to_pending_review` and `test_a3_reinstates_by_the_lead_ruling` red
- reinstate always to pending_review -> `test_reinstate_previously_listed_returns_to_listed` red
- drop the polyglot check -> `test_polyglot_rejected_415` red (4)
- skip the re-encode -> `test_reencode_drops_exif` and the route test red
- drop the O20 profile scope -> `test_idor_t7_cannot_delete_other_tutors_evidence` red (`204 == 404`)
- drop the GCS `response_disposition` -> `test_signed_url_disposition_attachment` red
```
## T10 review fixes
Lane `acc8b861` (6a489433), return 1/1, msg 57/57. SHA: `4f5cebeb` verified; `6df79243` verified
```text
RED (recorded before any behaviour code; the new names were added first so nothing failed on an ImportError):
- test_evidence_files: `b'/OpenAction'` was still in the stored PDF; the pixel cap raised Unsupported instead of TooLarge; `EXTRACTION_WORKER.pid() is None`
- test_tutor_approval_repo: DID NOT RAISE DocumentsNotOpenedError; the snapshot still had `filename`; the moderated-edit reinstate went to `listed`
- test_tutor_evidence: `201 == 415` for a scripted widget; `201 == 503` while the worker was busy
- test_web_admin_tutoring: `KeyError 'content_type'`; `200 == 409`
- test_storage_local: no `data:image/png`; test_storage_gcs: `KeyError 'response-content-type'`
- test_notify_email / test_tutoring_notify: a false pair was not refused; title "listed again" where "back in review" was expected
- n/a (regression guard): the R5 race test and test_web_tutoring_authz_admin; each is covered by a mutation below
MUTATION (all inside c2, which has the same code as c3; each went red, was restored with `cp`, and went green again):
- R1 store the original PDF bytes → pages_only_rewrite, junk_or_markup, t6_stores_a_pdf: red (3)
- R1 skip the active-content scan → kept_annotations: red (5)
- R2 run prepare_evidence in process → one_at_a_time `201==503` and runs_in_the_extraction_worker: red
- R2 flat 40 Mpx cap → pixel_cap tests: red (2)
- R3 skip the documents-opened check → 6 tests red (DID NOT RAISE, `200==409`)
- R4 ignore the pending edit → repo and route tests red (2)
- R5 drop `with_for_update` → `['added','added']`: red
- R6 put the filename back in the snapshot → red
- R8 drop `content_type` in A2, and drop GCS `response_type` → 3 tests red
- EXTRA send the "listed again" copy → inbox, email and route tests red (3)
```
## T11 web API hooks
Lane `a6440cc2` (6a489433), return 1/2, msg 5/15. SHA: `0d70febc` verified
```text
RED (against throwaway stubs, then replaced):
- tutoringQueryKeys.test.ts: "scans 70 hooks, each making exactly one API call": expected +0 to be 70
- tutoringApiErrors.test.ts: "knows every code in the status column": expected 40 parsed codes to deeply equal []
- persistAllowlist.test.ts: "enumerates a meaningful number of keys (at least 35)": expected 1 to be >= 35. The other new exclusion tests are absence tests with the mutation line below.
MUTATION (all inside the export, restored, then green):
- Tutoring key added to the allowlist (`["tutoring","public"]`): 3 persistAllowlist tests red (first: `publicTutors: expected true to be false`).
- Hook deleted (`useDeclineTutorBooking`): "scans 70 hooks" red (69 vs 70) and "covers each (method, path) once" red (`missing: POST /tutor/bookings/{}/decline`).
- One SPEC §c.1 row dropped: "parses exactly 70 rows" red (69 vs 70), plus 4 cross-checks (tally, §b.2, no-repeat, coverage).
- Not on the card, also run: the guard's data-clear line removed turns the `access_ended` clearing test red. `pending_limit` removed from the code list turns "knows every code in the status column" red.
```
Lane `a6440cc2` (6a489433), return 2/2, msg 15/15. SHA: `922f9310` verified; `0d70febc` verified
```text
RED (first failures before the code, on the new tests):
- R1: "asks the server exactly once": expected vi.fn() to be called 1 times, but got 109 times. My first version of this test hung the run. Its mock rejected on a microtask, so the refetch loop starved the timers. I killed it and the mock now rejects on a later macrotask.
- R2: "leaves nothing for dehydrate to write": expected 36 to be +0.
- R3: "defines AUDITED_READ…": expected undefined to deeply equal the four settings.
- R4: "lists the codes outside the status column": 5 listed codes vs 15 expected.
- R5, R6, R7, R9: `blockInvalidationKeys is not a function`; "creates no entry when none exists" got a Query; "sends {} when no reason is given": expected undefined to be '{}'; "wraps every path id in encodeURIComponent": `['${']` not null.
- R1: invalidate `["tutoring","own","students"]` instead of the list scope: 4 tests red (called 131 times; 274 times on re-render; state 'pending' not 'error'; invalidated key not the list scope).
- R2: remove `networkMode` from `useCreateBooking`: "sets networkMode always on every mutation" and "leaves nothing for dehydrate" red (`expected 1 to be +0`).
- R3: remove the `...AUDITED_READ` spread from `useAdminTutor`: "gives exactly those hooks the spread" and "hands exactly those four hooks' options" red (3 vs 4).
- R4: drop `invalid_rules` from the code list: "lists the codes outside the status column" and "one sentence of copy per code" red.
- R5: drop `studentClassAccess` from `blockInvalidationKeys`: 3 tests red.
- R6: `setQueryData` instead of `setQueriesData` in A11: "creates no entry when none exists" red.
- R7: drop `?? {}` from the student cancel: "useCancelStudentBooking sends {} when no reason is given" red.
- R9: unwrap `encodeURIComponent` on the T7 path id: 4 tests red (coverage, wrap check, name/order check, run-all-70).
```
(1 line(s) identical to an earlier return of this lane omitted.)
## T12 review fixes
Lane `aba8f14e` (6a489433), return 1/1, msg 75/75. SHA: `6df79243` verified
```text
RED:
- R1 test_web_tutor_reviews::test_sp3_and_t21_cursors_carry_the_review_id_and_no_instant: cursor k was `['2026-10-25T06:48:49…', '<id>']`, expected `['<id>']`.
- R2 test_web_tutor_reviews::test_a7_refuses_text_edited_after_queue_load: `assert None == 'c373843578496495'` (A6 item had no revision).
- R2 test_schemas_tutoring::test_moderation_dtos_carry_the_spec_text_revision: `{'revision'} <= {createdAt,itemId,kind,text}` failed.
- R3 test_tutor_review_repo::test_notice_revision_is_the_stored_moderation_instant: `assert 0 == 1792998510827468`; the web test expected key `…:approved:<micros>` but got `…:approved:0`.
- R6 test_tutor_review_repo::test_an_edited_review_requeues_behind_an_admin_who_paged_past_it: both edited texts were missing from `seen`.
- R4 rollback test and test_o21_a_review_cursor_must_name_a_review_of_the_listed_tutor: n/a (regression guard); covered by M4 and M7.
MUTATION (each red on T12f-c2, restored, green):
- M1 created_at back in the review cursor → cursor test red.
- M2 revision comparison removed → both A7 tests red ("Written later." approved unseen: 200 instead of 409).
- M3 notice revision fixed at 0 → both notice tests red.
- M4 create's recompute moved after commit → rollback test red (2 review rows, expected 1).
- M6 queue ordered by r.created_at → requeue test red.
- M7 tutor predicate dropped from the anchor subquery → O21 test red (200 instead of 422).
- M8 `text_changed` removed from the typed errors → tutoringApiErrors.test.ts red (2 of its tests).
```
## T12 reviews and moderation
Lane `ac1fdc97` (6a489433), return 1/1, msg 9/9. SHA: `1703c2af` verified
```text
RED:
- Repo file: 43 of 43 failed on the skeleton with `NotImplementedError`. That is a stub failure, not an assertion.
- Web file: first failure `assert 404 == 201`.
- Authz file: the route-set test failed.
- Concurrency and CLI files: fail on `NotImplementedError` (the errors list was not `[None, None]`; CLI exit code 1).
- Three tests passed vacuously on the skeleton (`test_o10_one_review_per_booking_is_a_database_rule_too`, `test_idor_s7_cannot_edit_another_students_review`, `test_a7_a8_ids_are_not_interchangeable`). I added positive controls to the last two. The first is a schema regression guard.
MUTATION (all inside the export, restored, rerun green):
- Card: counting every review instead of the latest per student turns `test_race_two_reviews_same_student_aggregate_counts_once` and `test_latest_review_per_student_counts_once` red.
- Card: dropping the 7-day guard turns `test_review_create_refused_before_notes_window_closes` and `test_s6_refusal_codes` red.
- Card: stopping the CLI after the first tutor turns `test_cli_recompute_all_restores_corrupted_aggregates_of_every_tutor` red.
- My own, each red on the named test:
 - Removing the tutor-row locks: `test_a_review_created_behind_an_unfinished_one_does_not_lose_it` and `test_an_edit_behind_…`.
 - Dropping the account-age guard: `test_account_too_new_409`.
 - Public text unfiltered: `test_review_text_public_only_after_approval`.
 - S7 author filters dropped: `test_idor_s7_cannot_edit_another_students_review`.
 - SP3 block predicate dropped: `test_sp3_blocked_pair_gets_404_but_a_parent_holds_no_blocks`.
 - 14-day edit guard dropped: `test_s7_refusals`.
 - Edit keeping the old text state: `test_review_text_public_only_after_approval`.
 - T18 tutor filter dropped: `test_idor_t18_cannot_reply_to_another_tutors_review`.
 - Removed reviews counted: `test_removed_review_leaves_aggregate`.
 - Moderation revision constant: `test_moderation_notifies_the_author_with_a_growing_revision`.
 - Tie-break ascending: `test_exact_created_at_tie_goes_to_the_greater_review_id`.
 - Idempotent repeat resending the notice: `test_moderation_notifies_the_author_with_a_growing_revision`.
 - Recompute not writing: `test_rank_score_written_with_rating_change`.
```
## T13 booking service
Lane `a5986af7` (6a489433), return 1/1, msg 23/23. SHA: `0b0f8bf1` verified
```text
RED (against the stubs: 128 failed, 1 passed, no ImportError):
- `test_booking_repo.py`: NotImplementedError from the stub `BookingService.create`.
- `test_booking_view.py`: NotImplementedError from the stub `build_booking_dto`.
- `test_booking_predicates_parity.py`: KeyError 'upcoming', because `BOOKING_WHEN_SQL` was still empty.
- `test_tutoring_concurrency_bookings.py`: `assert len(winners) == 1` failed with 0.
MUTATION (each in the export only, then restored and green):
1. Removed the students-row `FOR UPDATE` in create → `test_race_pending_limit_concurrent_requests_at_most_5` red ("the second transaction never queued").
2. Removed the core `has_reason` rule in `core/booking.py` → `test_tutor_late_cancel_without_reason_refused_by_core_422` red ('illegal_transition', 409 ≠ 'reason_required', 422).
3. Dropped the reason conjunct from the CAS `WHERE` → `…_refused_by_cas_when_core_bypassed` red (`ck_tutor_bookings_late_cancel_reason` raised IntegrityError).
4. Showed the meeting link before accept → `test_meeting_link_only_after_accept_to_participants_and_parents` red for both modes.
5. Made the create block check one-directional → `test_create_refused_when_blocked_either_direction[tutor]` red.
```
## T13 review fixes
Lane `a30e0190` (6a489433), return 1/1, msg 41/41. SHA: `415fcaa1` verified
```text
RED:
- test_tutoring_concurrency_bookings.py::test_race_sweep_vs_create_for_the_same_student_never_deadlocks[suspension,block]: `assert OperationalError(DeadlockDetected …) is None`
- test_booking_predicates_parity.py::test_transition_guards_count_elapsed_time_across_cairo_dst: `('cancel','student',None,'accepted',1 day 0:00:01, 2026-10-29 19:00Z) assert False is True`
- test_booking_view.py::test_system_cancel_reason_shows_cancelled_to_tutor[system]: `('Cancelled','system') == ('Cancelled','platform_admin')`; the new test_tutor_cannot_tell_a_block_from_a_platform_cancellation failed the same way
- test_booking_repo.py::test_accept_checks_only_the_detail_its_mode_keeps (4 cases): `BookingRefused` text_too_long / meeting_link_not_allowed / contact_details_not_allowed
- test_booking_repo.py::test_accept_refused_for_a_rejected_listing[draft,rejected]: `assert 'your' in 'this tutor is not taking requests right now.'`
- R4 test_tutor_late_cancel_without_reason_refused_by_core_422 and R5 test_failed_transition_writes_no_outbox_row: n/a (regression guard), proved by the mutations below
- tutoringApiErrors.test.ts "lists the codes outside the status column": failed, 7 codes missing
- test_quota_window_is_24_elapsed_hours_across_cairo_dst: n/a (the constant it imports is new, so before the fix it would only raise an ImportError), proved by mutation M2b
MUTATION:
- M1: removed the sweep pre-lock → sweep_vs_create red (40P01) in both variants; restored → green
- M2a: guard binds sent as timedelta (`'1 day'`) → the Cairo DST guard test red, while the UTC parity test stayed green; restored → green
- M2b: claim-only binding and quota binding sent as timedelta → the claim_complete case and the quota test red; restored → green
- M3: dropped the `system→platform_admin` mapping → 2 view tests red; restored → green
- M4: dropped the pre-CAS core check → the R4 test red 3/3 (an UPDATE statement was seen); restored → green
- M5: `_announce` queued its emails in a separately committed transaction → R5 test red (2 outbox rows survived the failure); restored → green
- M7: put back the old up-front validation of both details → R7 test red 4/4; restored → green
- M8: dropped the tutor message → draft and rejected cases red; restored → green
- WEB: dropped `note_empty` → the vitest list test red; restored → 19 passed
```
## T14 grants audit tutor view
Lane `a196d6e1` (6a489433), return 1/1, msg 17/17. SHA: `b8aae9c5` verified
```text
RED (stubs, no ImportError; 58 failed, 7 passed): each repo, view and parity test failed with NotImplementedError from its stub (`create`, `get`, `student_shared`, `build_student_detail_for_tutor`). The route tests failed on `assert 500 == 200`/`201`. Both race tests failed: "the second transaction never queued behind the first", and the 8 creates errored with NotImplementedError. The 7 that passed are guard, 422 and cursor tests that can pass before any code; they are regression guards.
MUTATION (each edited in the export, went red, `cp` restore, green again):
- roster consulted in `require_valid_grant` → `test_authz_cross_gate_class_teacher_without_grant_t20_404` red (200 != 404)
- live-grant lookup keyed on any tutor's grant, not the caller's → `test_idor_t20_other_tutors_grant_does_not_authorize` red
- history loaded before the audited gate → `test_audit_row_written_before_data_and_in_same_transaction` and `test_audit_failure_returns_500_no_body` red
- extra: `FOR SHARE` dropped on the live grant row → `test_t20_waits_for_an_inflight_revoke_and_then_refuses` red
```
## T14 review fixes
Lane `a65c22d2` (6a489433), return 1/1, msg 36/36. SHA: `ab8a6c25` verified
```text
RED (unfixed code, in WT):
- test_student_detail_view: `test_projection_is_a_function_of_the_tutor_day`: the 4 DTOs differ (`assert [{…}] == [{…}]`).
- test_tutoring_concurrency_grants:
 - `test_grant_create_does_not_deadlock_with_a_booking_create`: OperationalError DeadlockDetected (40P01).
 - `test_t20_does_not_deadlock_with_a_revoke_and_a_booking_create`: `AuditUnavailable` instead of `AccessEnded`.
- test_tutor_grant_repo: `test_pair_lock_is_the_booking_one_keyed_as_the_spec_prints_it`: `lock_pair_in_session is booking_repo.lock_pair_in_session` fails.
- test_web_student_tutor_access: `test_s9_refused_…`: draft `assert 409 == 404`.
- test_web_tutor_students (literal key paths) and test_grant_predicate_parity (half-open case): n/a (regression guard), each proved by a mutation below.
MUTATION (all in the export; each restored with `cp` and rerun green):
- R1 S9, drop the `KEY SHARE`: `test_grant_create_does_not_deadlock…` red with 40P01.
- R1 T20, drop the `KEY SHARE`: `test_t20_does_not_deadlock…` red (40P01 surfaces as `AuditUnavailable`).
- R2, elapsed days instead of calendar days: `function_of_the_tutor_day[14]`, `[15]`, the spring-forward test and the zone test are red.
- R2b, keep the teacher's flag instead of rebuilding it: only `test_inactive_flag_follows_the_tutor_day_across_spring_forward` is red.
- R3, add `lastActiveHour` to `StudentEngagementDTO`: `test_t20_json_has_no_key_outside_dto` red on `detail.engagement.lastActiveHour`.
- R4, private copy of the pair lock with the key reordered: the pair-lock pin test and `test_grant_writes_queue_behind_the_spec_pair_lock` are red.
- R5, expiry `>` changed to `>=`: `test_sql_grant_validity_is_half_open_at_expires_at` is red (`'at': (True, False)`); the 720-case test stays green.
- R5, drop the `FOR SHARE` on the live grant row: the sibling `test_t20_waits_for_an_inflight_revoke_and_then_refuses` is red ("never queued"). `test_race_revoke_vs_t20…` stays green, which confirms the review note.
- S9, restore the old 409 mapping: `test_s9_refused_for_unlisted_paused_or_blocked_tutor` red.
```
## T15 UI components C-17..C-24
Lane `a5467a21` (6a489433), return 1/1, msg 6/6. SHA: `0ec87ec4` verified
```text
RED (recorded against stubs with the right signatures, so none is an ImportError):
- ordinalDistribution: `expected [] to deeply equal ['A*','A','B','C','D','E','U']`
- gradeChangeSummary: `expected '' to be 'Change in grade while with this tutor'`
- slotPicker: `expected [] to deeply equal ['2026-10-30','2026-10-31']`
- bookingStatus: `expected [] to deeply equal [Array(8)]`
- ratingSummary: `expected 0 to be 3`
- safetyNotice: `expected '' to be 'Before your first session'`
- tutoringCatalogue: `no "## C-17 " heading in the catalogue`
MUTATION (all inside the export, restored, green again):
- Hide a zero rung: 5 red in ordinalDistribution.
- Change the fixed title: 2 red (title equals SPEC, aria sentence).
- Alter safety copy ("Do not share"): red on "equals the SPEC verbatim".
- Drop `expired` from the effective states: 5 red in bookingStatus.
- Group slots by UTC instead of the tutor zone: 8 red in slotPicker.
- Drop the "New below 3 students" guard: red.
- Rename the C-20 catalogue heading: red.
- Add an arbitrary `w-[300px]`: red on the token-only scan.
- `dismissible={false}` removed from the C-24 sheet: red. The first attempt stayed green because the test read a comment that quotes the string. I made all component-source tests read comment-stripped source and re-proved it on c2.
```
## T15 review fixes
Lane `a506bf76` (6a489433), return 1/1, msg 3/3. SHA: none in return
```text
**RED lines** (new tests against HEAD source, before the fixes): 43 failures, for example `distributionHidden is not a function`, `expected 'ClockCountdown' to be 'CalendarX'`, and `expected 'Phone numbers, email addresses and ch…' to be 'To keep everyone safe…'`. The stamp tests failed separately on `expected null not to be null` and `expected 1 to be 10`. The rating-threshold change was a refactor, so it has a mutation line instead of a RED one.
```
## T16 tutoring copy-lint rule
Return not found in the available transcripts (lane `{a['aid'][:8]}`: no RED/MUTATION/SHA/STATUS contract lines in its messages).
## T17 family booking routes
Lane `a72f9d72` (6a489433), return 1/1, msg 54/54. SHA: `26049494` verified
```text
RED: tests/test_web_tutoring_booking.py: test_sp5_slots_window_duration_and_bounds `status_code == 200` got 404 {"detail":"Not Found"} (skeleton routers had no routes) | test_web_student_bookings.py: test_s1_… 404 Not Found | test_web_parent_bookings.py: test_pa1_… 404 Not Found | test_web_tutoring_authz_bookings_family.py: test_tutoring_private_routes_send_no_store `len(declared) == 14` got 0
MUTATION: drop the per-call link check in child_viewer -> test_authz_parent_actions_refused_after_unlink (+ test_pa_routes_403_…) red on c2; restored -> green
MUTATION: student's studentId ignored (subject None) -> test_o6_sp6_subject_is_the_student_or_a_linked_child red (201 instead of 403 not_self); restored -> green
MUTATION: hidden_tutor_error passes codes through -> test_sp5_sp6_refused_for_unlisted_paused_or_blocked_tutor red (409 tutor_not_listed); restored -> green
MUTATION: SP5 ignores the student's blocks -> same O11 test red (200 for blocked_by_student); restored -> green
MUTATION: cursor tag without `when` -> test_s1_…_when_tagged_cursor and test_pa1_… red (200 instead of 422); restored -> green
MUTATION: no send_after_commit in apply_transition -> test_s3_commits_when_inbox_write_raises and test_s3_cancel_tells_… red; restored -> green
MUTATION: student router built without TutoringRoute -> test_tutoring_private_routes_send_no_store red; restored -> green
```
## F5-17 T17 review fixes
Return not found in the available transcripts (lane `a57be7e6` ended on a session-limit notice; the task was re-dispatched in a later lane listed in this ledger).
## F5-17 T17 review fixes
Lane `a0aefe28` (c4e7dcea), return 1/1, msg 21/21. SHA: `65c23798` verified
```text
RED: test_web_tutoring_booking.py::test_sp5_sp6_dates_at_the_ends_of_the_calendar_are_422_never_500: `OverflowError: date value out of range` | test_web_student_bookings.py::test_s15_shares_t20s_preferences_provider_and_dto: `assert <T20 provider> in {_guard, <student_bookings provider>}` | 3a, 3b, 3c, 3d, 3e: n/a (regression guard; they passed at HEAD, proofs below)
MUTATION: SP5 without the `from > date.max - 28d` check -> test_sp5_sp6_dates… red (OverflowError); restored -> green
MUTATION: SP6 without the calendar bound -> same test red at :589 (OverflowError); restored -> green
MUTATION: HEAD's student_bookings.py (copied provider and DTO) -> test_s15_shares… red; restored -> green (only this test was run, so S15 never reached the shared DB)
MUTATION: shared provider but a local `settings_dto` copy wired into S15 -> test_s15_shares… red; restored -> green
MUTATION: `_LINK_STATES` + "cancelled" in the export's copy of booking_view.py -> test_s3_cancel_tells… red (meetingLink) and test_pa4_late_cancel_409… red (locationDetail); restored from `git show HEAD:` -> green
MUTATION (extra, 3a): `require_linked_child` removed from `_requester` -> test_o6_sp6_subject… red ('Student not found.' != 'Child not found.'); restored -> green
```
## T18 tutor booking routes
Lane `aff8d1c5` (6a489433), return 1/1, msg 34/34. SHA: `4fc13795` verified
```text
RED: tests/test_web_tutor_bookings.py: `test_t9_lists_own_bookings_by_when_with_typed_cursor` `assert first.status_code == 200` got 404 (stub router with the provider only, no ImportError)
RED: tests/test_web_tutoring_authz_bookings_tutor.py: `test_router_serves_exactly_spec_rows_t9_t17` `set() == {9 SPEC pairs}`
MUTATION: studentShared read through `require_valid_grant` (the audited gate) -> test_t10_student_shared_writes_no_audit_row red on c2 (3 `detail` audit rows); restored -> green
MUTATION: `meeting_link_allowed` accepts `http:` -> test_t11_meeting_link_allowlist_and_location_required red (200 != 422); restored -> green
MUTATION: T11 guarded by `require_tutor_profile` -> test_authz_suspended_tutor_write_routes_409[accept-suspended / accept-closed] red (404 != 409); restored -> green
MUTATION (extra): studentShared queried once per row -> test_query_budget_t9_two_statements red; restored -> green
MUTATION (extra): T9 drops `state` -> test_t9_state_filter_uses_effective_predicates red; restored -> green
```
## F5-T test hardening T18 T19 T20
Return not found in the available transcripts (lane `a8802f29` ended on a session-limit notice; the task was re-dispatched in a later lane listed in this ledger).
## F5-T test hardening T18 T19 T20
Lane `a8b360a2` (c4e7dcea), return 1/1, msg 4/4. SHA: `596c25df` verified; `a3815db9` verified; `fd066e99` verified
```text
RED: n/a (regression guards). I did not run each new test before the code, so the mutations below are the proof. The one new production behaviour is the PA7 cursor tag, and test G covers it.
MUTATION (run inside c2, restored from the original text afterwards; each has a stated test id and went red):
- A. T9 refuses suspended or closed (list_bookings uses require_writable_tutor_profile): test_authz_t9_list_stays_readable_when_suspended_or_closed[suspended] and [closed] red (2 failed, 40 passed).
- B. Drop `g.tutor_profile_id = :tutor_id`: test_ever_granted_counts_this_tutors_grants_only red (1 failed).
- C. Block hold reads active blocks only (`removed_at IS NULL`): test_removing_a_student_block_does_not_lift_the_hold red, and the parity test red on `removed_recent` (2 failed).
- D. Observations read for every subject (`if True`): test_query_budget_a_hold_over_every_subject_skips_the_observations_statement red.
- E. PA6 `include_classes=True`: test_query_budget_pa6_never_reads_the_childs_classes red.
- F. PA6 `viewer="student"`: test_pa6_shows_no_class_even_if_the_repository_returned_one red.
- G. PA7 tag without the child: test_pa7_cursor_is_bound_to_the_child_it_was_minted_for red.
- H. PA router on a plain APIRoute: test_authz_pa6_pa7_anonymous_is_401_no_store red (4 failed, 2 passed).
- I. S12/S13 router on a plain APIRoute: test_s12_s13_anonymous_is_401_no_store_and_writes_nothing red (7 failed, 2 passed). The 7 failures include the existing route-class and no-store tests as well as the new one.
```
## T19 outcome figures
Lane `acf31e59` (6a489433), return 1/1, msg 48/48. SHA: `e26c57ec` verified
```text
RED: test_tutor_outcomes_repo.py: test_base_world_is_sufficient_and_counts_each_member_once -> `assert outcomes is not None` (stub returned None)
RED: test_outcome_eligibility_parity.py: test_sql_attempt_eligibility_equals_core_over_generated_inputs -> `assert actual == expected` (eligible rows read False)
RED: test_web_tutoring_outcomes.py: test_sp4_for_parent_and_student_with_no_store_and_dto_keys -> `assert response.status_code == 200` (404); test_observations_statement_with_no_members_reads_nothing passed on the stub = n/a (regression guard)
MUTATION: drop boundary_source='exact' -> test_excludes_estimated_boundary_attempt[subject_default,global_default] + attempt-parity[both ladders] red (4) on <T>; restored -> green
MUTATION: membership via completed_at instead of accepted_at -> test_outcomes_marking_complete_no_show_changes_nothing red (also red at the byte comparison after `complete` with the sufficiency precondition removed); restored -> green
MUTATION: exclusion from active blocks only (active_block_between_sql) -> test_excludes_student_who_ever_blocked_tutor + test_sql_cohort_facts_equal_core... red; restored -> green
MUTATION: block date dropped from the hold -> test_student_block_hides_both_figures_for_90_days... + cohort-facts parity red; restored -> green
MUTATION: interval '120 days'/'180 days' instead of make_interval(secs) -> test_observation_windows_are_elapsed_time_in_a_cairo_session red; restored -> green
MUTATION: T8 listing-state check dropped -> test_idor_t8_preview_omits_outcomes_when_suspended_or_rejected red; SP4 block anti-join dropped -> test_sp4_404_for_unlisted_paused_or_blocked_tutor + test_outcomes_for_viewer_hides... red; restored -> green
MUTATION: membership without the state filter -> test_late_cancel_leaves_outcomes_unchanged (after the slot moves into the past) + test_cancelled_declined_expired_and_unended_sessions_never_count red; deleted_at filter dropped -> test_excludes_deleted_attempt red; restored -> green
```
## F30-6 T19 cursor leak
Lane `a36e442a` (c4e7dcea), return 1/1, msg 30/30. SHA: `04cde6fc` verified
```text
RED:
- tests/test_web_tutor_students.py::test_t19_cursor_carries_no_timestamp: `assert not re.search('\d:\d', '{"e":"tutor_students","k":["2026-10-25T22:31:07.123456+00:00","<uuid>"]}')`, matched '2:3'
- tests/test_web_tutoring_authz_grants.py::test_t19_cursor_of_another_tutors_grant_is_invalid_cursor: `assert 200 == 422` (tutor B's list was paged from tutor A's cursor)
- tests/test_tutor_grant_repo.py::test_t19_paging_is_stable_when_the_anchor_grant_is_revoked_between_pages: n/a (regression guard: the old cursor carried the instant, so a revoked anchor already paged correctly). Proven by M3 below.
MUTATION:
- M1, timestamp put back in the cursor -> test_t19_cursor_carries_no_timestamp red on <T> (`\d:\d` matched); restored -> green
- M2, profile scope dropped from the anchor join -> test_t19_cursor_of_another_tutors_grant_is_invalid_cursor red (`200 == 422`); restored -> green
- M4, scope dropped from the empty-page check `_is_grant_of` (AND -> OR) -> same IDOR test red (`200 == 422`); restored -> green
- M3, anchor must still be live (`AND anchor.revoked_at IS NULL`) -> stability test red (`[] == [tied[1], older]`); restored -> green
```
## T20 settings and parent views
Lane `a118528c` (6a489433), return 1/1, msg 29/29. SHA: `08bebc66` verified
```text
RED: tests/test_web_student_tutoring_settings.py: test_s12_defaults_when_never_saved_and_a_read_writes_nothing `assert 404 == 200`
RED: tests/test_web_parent_tutor_access.py: test_pa6_returns_only_childs_grants_also_teaches_empty `assert 404 == 200`
RED: tests/test_web_tutoring_authz_parent_sharing.py: test_authz_o22_other_child_403_unknown_404 `(pa6) assert 404 == 200`
RED: test_pa7_writes_no_tutor_access_audit_row, test_pa6_writes_no_tutor_access_audit_row: n/a (absence) -> M1
 (all 23 tests failed on missing routes, never on an ImportError: skeleton routers were in place first)
MUTATION: M1 PA7 inserts a tutor_access_audit row -> test_pa7_writes_no_tutor_access_audit_row red on <T> (`assert 4 == 2`: parent reads appeared in the log); restored -> green
MUTATION: M2 PA6 skips require_linked_child (role guard kept) -> test_authz_o22_other_child_403_unknown_404 red (another family's grant served with 200), test_authz_o7_link_checked_on_every_call red ([200,403] != [403,403]); restored -> green
MUTATION: M3 PA6 with viewer="student" and include_classes -> test_pa6_returns_only_childs_grants_also_teaches_empty red ([['Physics 10A'],[],[]] != [[],[],[]]); restored -> green
MUTATION: M4 PA7 uses S11's cursor tag -> test_pa7_cursor_has_its_own_tag red; restored -> green
```
## T21 blocks and sweeps
Lane `a3b1516e` (c4e7dcea), return 1/1, msg 8/8. SHA: `474155a9` verified
```text
RED: tests were run first against stub modules: 102 failed, 21 passed.
- The 21 that passed are role-guard 403/401 cases and the extra-field 422. They are regression guards.
- Web files failed first on `assert 501 == 404` (idor_b2), `assert 501 == 200` (A5) and `assert 501 == 409` (authz_blocks).
- The sweeps and blocks_repo files failed with NotImplementedError from the stubs, not an assertion.
- The concurrency file failed on `assert blocker.error is None`.
MUTATION: each run on the export, each restored and back to green.
- sweep tutor lock FOR UPDATE→FOR SHARE → test_race_suspend_vs_booking_create… red (the booking stayed `requested` on a suspended tutor)
- block deletes school enrolments too → test_block_removes_school_less…keeps_school… red on both sides
- suspension uses remove_all → test_suspension_…_tutoring_students_only red (5≠3)
- upsert without `WHERE removed_at IS NOT NULL` → test_b2_twice_…keeps_notes_frozen red (notesFrozen false) and test_block_on_an_active_row_writes_nothing red
- block row stamped with clock_timestamp() → test_block_insert_cancel_and_revoke_share_one_now red
- student O13 rule reads the tutor's block → test_b2_answers_the_same_…[student] red (404 vs 201)
- tutor O13 relation dropped → test_o13_tutor_may_block_only… red, plus the route 404 test
- CB-7 check dropped → test_authz_suspended_tutor_write_routes_409 red
- student notice off on a tutor's block → test_tutor_block_tells_the_student_exactly_what_a_suspension_does red
- lift without updated_at → test_unblock_sets_removed_at_and_updated_at… red
- test_tutor_block_leaves_outcomes_unchanged carries its own red control: the same block made by the student changes the figures.
```
## T22 discovery screens
Lane `a3f2c20b` (c4e7dcea), return 1/1, msg 5/5. SHA: `c1318c35` verified
```text
RED:
- tutoringDiscovery: `expected '' to be 'Find a tutor for IGCSE Maths, Additio…'`.
- tutoringBookingErrors: `not_linked has no booking handling: expected [] to include 'not_linked'`.
- tutoringRobotsMeta: red before code. I recorded no exact assertion line for it.
- I ran these against throwing stubs, because a missing import is not a red.
MUTATION (all on T22-c4, restored, then green):
- Dropped the `slot_taken` mapping: 4 tests red in tutoringBookingErrors.
- G-17 ignores `indexable`: 2 tests red (opt-out and fail-closed).
- Public address writes `day`: "the public directory has no availability filter" red.
```
## F6-22 T22 review fixes
Lane `a45de2ba` (c4e7dcea), return 1/1, msg 1/1. SHA: `357a337e` verified
```text
RED: tutoringDiscovery.test.ts: `slotAfterLengthChange` was not a function. tutoringBookingErrors.test.ts: `noteFieldTargets` was not a function. tutoringRobotsMeta.test.ts: `tutorCardId` was not a function.
MUTATION:
- Finding 1 (Length change drops the slot): `slotAfterLengthChange` returned the slot unchanged -> "drops a chosen time when the length changes" red on the export; restored -> green.
- Finding 2 (parents told when sharing starts): removed `SHARE_PARENTS_TOLD_LINE` from `shareSheetLines` -> "the share sheet tells the student their linked parents are told" red; restored -> green.
- Finding 6 (worker card predicate): dropped the `i` flag on robotsMeta's `UUID` -> "agrees with the worker about what a card path is" and "serves the directory and a card only at their canonical paths" red; restored -> green.
```
## T23 student session screens
Lane `affc0b05` (c4e7dcea), return 1/1, msg 2/2. SHA: `5ab1e015` verified
```text
RED: both test files: n/a. I wrote them first but did not record a failing run before the code, so each guarded rule carries a MUTATION line instead.
MUTATION (12 edits in the export, each red, restored green at 96/96):
- State turns Cancel on → "an empty allowedActions renders nothing" red.
- Inside-24h sentence reworded → 3 red.
- Late-cancel reason escaped → plain-text test red.
- System cancellation repeats the stored reason → 5 red.
- View renders the reason as HTML → source scan red.
- Class line always added → stop-sharing test red.
- Closed tutor reads differently from `tutor_unavailable` → 2 red.
- View reads `allowedActions` itself → source scan red.
- Any URL is linked → 2 red.
- Parent acts without being the requester → red.
- `blocked` label changed → red.
- Parent footnote loses the child's name → red.
```
## F6-23 T23 review fixes
Lane `a928c020` (c4e7dcea), return 1/1, msg 3/3. SHA: `8edd16ab` verified
```text
RED:
- tutoringSessionView.test.ts: `reviewView` returned `kind:"tooNew"`, not `unavailable`. The same file also went red on the year label and on `reviewEditHint`. 10 tests were red before code across the two edited test files.
- tutoringAccessView.test.ts: `unblockSheetCopy` was missing, so the Unblock sheet test failed.
- tutoringSessionScreens.test.ts: n/a (regression guard). It was written against the existing code and passed at once, so it has the MUTATION lines below instead.
MUTATION (every one went red on the export, then I restored the file and it went green):
- Missing Review inferred as "account too new" -> `reviewView` "not explained by guessing" red.
- Thread ignores `post_note` -> "thread says yes but post_note is missing" red.
- View skips the C-24 gate -> "unread: the note is not sent" red.
- Cancel drawn from `effectiveState==="accepted"`:
 - in the view (button and action row) -> "no Cancel in allowedActions", "tutor-only action" and "parent gets Cancel" red.
 - in `sessionActions` -> 8 red.
 - Changing the action-row guard alone left the tests green, but it only draws an empty section and no button, so it is not a real change in behaviour.
- Sheet drops every line but the first -> 3 red.
- Class line always shown -> 2 red.
- Year removed from the label -> 3 red.
- Unblock acts on one tap -> "never calls the mutation from the button" red.
- Heading focus without the unmount handoff -> "focus order" red. Focus on the state-change effect and a missing classes focus handoff each also go red.
- Edit hint removed -> red.
- Parent can cancel a booking they didn't make -> red.
```
## T24 teacher tutoring screens
Lane `afa3eb68` (c4e7dcea), return 1/1, msg 4/4. SHA: `998769b2` verified
```text
RED: the first run was an ImportError, so I stubbed the exports with wrong behaviour and recorded these first failing assertions.
- Availability: `expected +0 to be 15`.
- Profile steps: `expected '' to be 'Your public card is on the open web, …'`.
- Session actions: `expected ['review','post_note'] to deeply equal []`.
MUTATION: each of the 15 mutations below went red on c3 and green once restored. The mutations were:
- Step size changed to 5 minutes.
- Midnight split removed.
- Overlap check made to look only at the next window.
- DST note reworded.
- `headline` dropped from the moderated list.
- `paused` treated as needing review.
- `indexable` treated as needing review.
- Re-review line shown for any state, not just a listed profile.
- Search notice reworded.
- Blank cancel reason accepted.
- Actions not limited to `allowedActions`.
- Meeting link accepted without https.
- Extra host added to the allowlist.
- "A parent" shown to the tutor.
- Own block no longer recognised.
```
## F6-24 T24 review fixes
Lane `a8ee841e` (c4e7dcea), return 1/1, msg 3/3. SHA: `766ae7d1` verified
```text
RED: tutorSessionActions.test.ts: 6 new tests red before code (sessionQueuesView, lateCancelNeeded, shouldRefetchBooking, reasonLength were missing exports, so TypeError "is not a function"; not counted as a RED)
RED: tutoringProfileSteps.test.ts: 3 red before code (413 under-10 MB message, displayInitial, ß sent as typed). I did not capture the assertion text of those three before editing.
MUTATION: queues drawn for rejected -> "draws the queues for every state..." and "explains a suspended or closed..." red on <T>; restored -> green
MUTATION: displayInitial always upper-cases -> "upper-cases an initial only when..." and "sends a sharp s as typed..." red; restored -> green
MUTATION: 413 always says 10 MB -> "does not call a file over 10 MB the cause..." red; restored -> green
```
## T25 reports and cross-cutting
Lane `a8100885` (c4e7dcea), return 1/1, msg 77/77. SHA: `adea2610` verified
```text
RED: test_tutoring_reports_repo.py: NotImplementedError from the skeleton `file()`. Two regression guards passed (allowlist equals §i.4, cursor bound to its state), each proved by a mutation below.
RED: test_web_tutoring_reports.py: `assert 501 == 201`. The 422/403 guard tests passed before code: regression guards.
RED: test_web_admin_tutoring_reports.py: `assert 501 == 200`. test_web_tutoring_authz_reports.py: `AssertionError: other student` (501≠404).
RED: test_tutoring_cross_cutting.py: n/a (regression guard). All 5 passed on the skeleton; proved by M1-M3b.
MUTATION (each red on <T>, then restored with cp, then green):
- M1: blocks router without `route_class=TutoringRoute` → no_store_unauthenticated + p1_p3_cacheable red.
- M2: `require_tutor_profile` returns a default profile → 404_no_tutor_profile red.
- M3: filter prefix `/api/tutor/`→`/api/tutors/` → exactly-70 red. M3b: R1 prefix `/report` → `69 == 70`.
- Visibility: a note visible through any booking with the tutor → idor_note red. A reply judged without its review → idor_reply red. Participants lose a paused profile → paused-participant test red.
- Freeze and email: no freeze → freezes_thread red. `require_verified_email` on R1 → without_verified_email red (403).
- A10 log: no thread-view row → a10_writes red. Failed log write swallowed via savepoint → same test red (200≠500).
- Allowlist and labels: allowlist bypassed → drops_every_key red. Student display name used as author → both party-label tests red.
- A11 locks and transaction: sweep in its own transaction → suspend_rolls_back red. Tutor row `FOR SHARE` instead of `FOR UPDATE` → lock-order test red.
- Rules: quota check `>` instead of `>=` → quota_429_after_20 and repo quota red. No `disputed_outcome`/booking-target check → 2 not_applicable cases red. Freeze always lifted → keeps_the_freeze red.
```
## F7-25 T25 review fixes
Lane `aa8859b4` (c4e7dcea), return 1/1, msg 74/74. SHA: `957d4e20` verified
```text
RED: reports_repo: upgrade x3, details merge -> ReportRefused report_exists; summary -> KeyError 'declineReason'; deterministic race -> 4 of 4 filed; barrier rounds -> 22 == 20; safety-over-safety / other-reason re-report -> n/a (regression guard)
RED: web_tutoring_reports upgrade -> 409 report_exists | web_admin: KeyError 'tutorListingState', KeyError 'locationDetail', A11 snapshot still has 'body', suspend-when-out x2 and platform-cancel x2 -> 409 resolution_not_applicable; content_hidden-when-hidden and dismissal with a seeded note -> n/a (regression guard)
RED: authz: grant-only tie -> 404; blocked student on review -> 404 == 201; on reply x2 -> not_found | booking_repo -> TypeError unexpected kwarg 'at'
MUTATION: #1 upgrade branch off -> 4 tests red; restored -> green
MUTATION: #2 _lock_reporter removed -> both race tests red; restored -> green
MUTATION: #3 location_detail=None; cancel reason always stored; student branch returns stored -> summary tests red (each); restored -> green
MUTATION: #4 out-of-service return removed / platform-cancel return removed / _hide refuses already-hidden -> the 3 idempotence tests red (plain hide test stays green); restored -> green
MUTATION: #5 body kept in A11 snapshot -> note-text test red; with_notes=True on A11 -> seeded-note dismissal red; restored -> green
MUTATION: #6 block clause put back -> review + reply x2 red; #7 grants clause dropped -> grant test red (booking test green); restored -> green
MUTATION: #8 repo at=None -> suspend stamp red; booking_repo now() -> `at` test + suspend stamp red; restored -> green
```
## T26 tutor-student screens
Lane `ab16fb57` (c4e7dcea), return 1/1, msg 5/5. SHA: `1b662cc5` verified
```text
RED: `tutorStudentView.test.ts`: first failing assertion `expected '' to contain 'Maya R.'` (stub modules). 33 of 44 failed; the other 11 are controls such as the teacher page still drawing the removed controls.
MUTATION (all on `<T>`, restored, green again, files `cmp`-identical to the worktree):
- `attemptAction` passed, or `footer` passed, or `showAcknowledged` dropped -> "draws none of them for the tutor" and "passes no attempt action and no footer" red.
- A time leaks (instant not cut to a day), or relative time in `recorded` -> the "no clock time and no relative time" tests red.
- Ended branch removed, server message leaking into the ended heading, or a retry button on the ended state -> the access_ended tests red.
- Screen calling `removeQueries` -> "leaves clearing the cache to the access_ended guard" red.
- Extraction dropping the teacher's `footer` or `attemptAction` -> "finds every one of them in the teacher's page" red.
```
## F7-26 T26 review fixes
Lane `a57f24e6` (c4e7dcea), return 1/1, msg 4/4. SHA: `24cce6bc` verified
```text
RED: tutorStudentView.test.ts: 7 failed before code (the 53rd test, added after, went red on mutation M2c).
- Zone: `sharedLine(..., "America/Los_Angeles")` gave "on 9 Jan 2026", expected "on 8 Jan 2026".
- Not-found: `isStudentNotFound(422 validation list)` was false.
- Title: `TUTOR_STUDENT_TITLE` was undefined.
- Dash: `lastActive("")` was "Never".
- The duplicate-key test and the pin tests passed before code. Both are regression guards; mutations below.
MUTATION (each red on the export, restored, then green):
- F1: removing `-${index}` from the trend key or the attempt key (StudentDetail.tsx) -> "gives two same-day attempts and two same-day trend points distinct React keys" red.
- F9: renaming the Actions header -> the markers test, the header-order test and "finds every one of them in the teacher's page" red. Adding a column -> header-order test red.
- F4: any 404 treated as not-found -> "only the API's not_found..." red.
- F5: unplaced activity back to "Never" -> dash test red.
- F2: `sharedLine` ignoring the zone, or the screen not passing it -> "the sharing line is cut in the tutor's zone" red.
- F2: the screen using a Cairo-zoned `dates` -> "the page cuts every date it draws in the profile's zone" red.
- F6: the hidden h1 back to "Student detail" -> "T-20 has one title" red.
```
## T27 parent screens
Lane `aac545f3` (c4e7dcea), return 1/1, msg 9/9. SHA: `e4cf51d6` verified
```text
RED: parentTutoring.test.ts: `expected '' to be '/parent/tutors/t%201'` (stub lib, 40 of 49 failed). The 9 that passed on the stub are absence guards; each has a MUTATION line.
MUTATION (T27-c3, restored, then green 49/49):
- parent form uses student audience -> "is the shared form in its parent audience..." red
- first note sent for any audience (booking-form.tsx) -> "...only ever sends a first note for a student" red
- requester check dropped (sessionView.ts) -> "shows Cancel only when this parent requested..." red (3 failing)
- revoke hook imported, or a Stop sharing button drawn -> "has no revoke control..." red
- linked-list lookup returns the first child, or preselect trusts the address -> "finds a linked child..." and "preselects..." red
- 404 copy implies a block -> "reads a 404 as 'not taking bookings'..." red (3 failing)
- parent next target not mapped -> "maps the student target..." red
- second-person grant words -> "covers every status..." red
- no Tutoring link on the overview -> "links to P-05 once..." red
- ChildScope shows the first child for an unknown id -> "is a plain not-found..." red
- parent notes can post -> "hands the shared view the parent's wiring..." red
- Block offered on a tutor page -> "a tutor's page offers Book and Report..." red
- hidden-tutor page without an h1 -> red
- mutation script `.omc/scratch-t27/mutate.py` edits only inside the export, not with the Edit tool
```
## F7-27 T27 plus shared copy fixes
Lane `ac494717` (c4e7dcea), return 1/1, msg 2/2. SHA: `8a2df021` verified
```text
RED (first failing assertion before code):
- postLoginTarget.test: a parent with `/student/tutors/<uuid>` got `/parent`, not `/parent/tutors/<uuid>`.
- parentTutoring.test: 15 failures in total, the first being `/parent/tutors/t1` where `/parent/tutors/t1?child=c1` was expected.
- tutoringDiscovery.test: the fallback notice had no "Your child can opt out".
- tutoringSessionView.test: `completeHint is not a function`.
MUTATION (each went red on the export, then green after restoring from WT):
- Mapping removed from postLoginTarget -> `postLoginTarget.test` "maps the student's tutor page to the parent's page" red.
- tutor_suspended detail changed to "The tutor blocked {child}." -> parentTutoring red. The first failure printed was "reads a tutor-side ending the same"; the new `/block/i` pin test should fail on the same mutation, but I did not read its own line.
- parentNextTarget accepts any segment -> "maps only a real tutor id" red.
- parentNext.ts gains an import -> "keeps the Login bundle small" red.
- childErrorFor ignores the chosen child -> "Booking for error" red.
- P-05, P-06 and P-08 tutor links each drop `?child=` -> red, one mutation per link.
- Counting notice back to lowercase -> tutoringDiscovery red.
- completeHint ignores the viewer -> tutoringSessionView red.
- TutorFailure h1 removed -> red.
- booking-form's `heading={false}` removed -> red.
```
## T28 admin screens
Lane `a73812fe` (c4e7dcea), return 1/1, msg 8/8. SHA: `572a3cd4` verified
```text
RED: `adminTutoring.test.ts`: against a stub module the first failure was `expected +0 to be 2000` (`DECISION_NOTE_MAX`), 56 of 61 tests failing. The screen-wiring tests were added after the lib and proved by mutation instead.
MUTATION, each red on the export, restored, green:
- Reject/suspend note required: 2 tests red.
- Approve gate ignoring the documents box: 3 red.
- Approve gate ignoring unopened files: 4 red.
- Approve button's `disabled` removed: screen test red.
- Moderation drops the revision: 2 red, plus the screen test with the revision removed from the call.
- `booking_cancelled` after start: red.
- `booking_completed` without the `disputed_outcome` reason: red.
- Mock banner shown for any non-undefined value: 2 red.
- Student author name leaking into the thread: 2 red.
```
## F7-28 T28 review fixes
Lane `a2d7980e` (c4e7dcea), return 1/1, msg 3/3. SHA: `81296f44` verified
```text
RED (adminTutoring.test.ts): 15 failed before code, then 111 green.
- Items 1/2: `threadNotes` kept `[]`; suspend was offered for suspended/closed/draft.
- Item 3: close text lacked "It also removes students from the classes…".
- Item 4: note_too_long still said "2000 characters".
- Item 5: snapshot area/subjects came out as JSON.
- Items 8/9/10/11: `resolveReadiness`, `resolutionStillOffered`, `cancelWindowMs`, `isAlreadyResolved`, `completedByLabel` and the reload button were still stubs.
- The approve guard test (item 6), the DecisionDialog tests (item 7) and the resolved-with-notes render already passed before code. They are regression guards, each with a mutation below.
MUTATION (each ran in the export and went red on that test; restored, then green):
- Item 6, approve guard removed → "sends nothing when the form is submitted while the gate is shut".
- Item 7, confirm `disabled={false}` → "keeps the confirm button disabled while a required note is blank".
- Item 8, note check dropped in `resolveReadiness` → "is ready only with a choice, a note…".
- Item 1, `threadNotes` returns `current` → "keeps the notes of the last read…".
- Item 2, `canSuspend` always true → "does not offer the suspension for a tutor who is suspended, closed or still a draft".
- Item 9, `resolutionStillOffered` always true → "checks a choice again at submit time".
- Item 9, `cancelWindowMs` guard removed → "says how long until the session starts…".
- Item 10, reload shown for every error → "offers to reload the report after an already-resolved refusal, and only then".
- Item 11, raw `.replace("_"," ")` → "says who completed the booking in words".
- Item 5, `.name` branch removed → "shows the name of a {code, name} value…".
- Item 4, 2000 in the sentence → "covers the codes the admin routes send…".
```
## T29 e2e seed data
Lane `ad62aa5c` (c4e7dcea), return 1/1, msg 7/7. SHA: `0f618af9` verified
```text
RED (blank cohorts and empty plan, so every failure is an assertion):
- sufficient test: `assert 0 >= 5`
- insufficient test: `assert 0 < 0`
- every-effective-state test: `assert set() == {'accepted', ...}`
- payload shape test: `TypeError ... unexpected keyword argument 'tutoring'`
- database tests: `KeyError: 'tutors'`
MUTATION (all on the export, each restored and green):
- Drop student s5: the sufficiency test goes red on `assert 4 >= 5`, as do the k-floor test and the database tests.
- Drop the `expired` plan row: `test_every_effective_state_is_planned` and the database state test go red.
- Drop `boundary_source="exact"`: `seed_tutoring_fixture` raises RuntimeError. 13 database tests error and 1 fails.
- Drop the indexable-false update: `test_tutor_listing_states_and_indexing` goes red on `assert True is False`.
- Move the tutor late cancel out of the 24h window: the planned late-cancel test and the database late-cancel test go red.
- Delete one `tutoring.*` line from the spec's SHAPE: the lockstep test goes red on "seeded, not declared".
```
## T31 Phase 4 docs
Lane `a480acff` (c4e7dcea), return 1/1, msg 5/5. SHA: `eb662d52` verified
```text
RED: web/tests/unit/dataHandling.test.ts: the suite failed to load because `tutoringSections` was not exported (`Cannot read properties of undefined (reading 'flatMap')`). That is a missing export, not an assertion, so no assertion-level RED was recorded.
MUTATION:
- "60 a day" changed to "50 a day" in the copy: "pins the email cap and the mock-provider behaviour" red on T; restored, green.
- A cited source path renamed to a file that does not exist: "gives every section a comment that cites at least one file that exists" red on T; restored, green.
```
## T32 e2e journeys (live)
Lane `a24a9093` (c4e7dcea), return 1/2, msg 8/11. SHA: none in return
```text
MUTATION (one export run, `/tmp/t32-mut.sh`, with the D1 bypass): six wrong values each failed on the mutated assertion.
- Grade count off by 7: "grade A* has 0 student(s)".
- Wrong tutor name on P-08: not found.
- Audit count after revoke expected +1: "Expected: 4, Received: 3".
- First-note field expected on the parent form: count 0.
- Raced start expected held by 2 requests: "Received: 1".
- Wrong S-34 smoke heading.
- Seed fixes: `tests/test_seed_e2e.py` has a "child is verified" test and a "stdout is one JSON document" test. Reverting each fix in an export turned its test red.
```
Lane `a24a9093` (c4e7dcea), return 2/2, msg 11/11. SHA: `af46e47e` verified; `025771f4` verified
```text
MUTATION (empty-state assertion): in a scratch export I pointed test (a) back at `declining` and ran parent-journey and staff-inbox through that export's wrapper.
- "parent inbox renders for a parent" failed on `getByText('When your child may need support')`.
- The other 7 tests passed, and the export is deleted.
```
## T33 UI QA (live)
Lane `ae6159c5` (c4e7dcea), return 1/1, msg 10/10. SHA: `b9abe558` verified; `3ef7b28e` verified
```text
RED: `auditTutoringRegistry.test.ts`: n/a (absence), mutation instead. Red before code for S-38 focus (`body`) and G-17 loading (no `h1`), both found by the registry predicates.
MUTATION, red on the export, each restored green:
- G-16 default `ready` pointed at `/login`: "every ready waits on its own route's pathname" red.
- `waitForExpectation` without the pathname test: "rejects a login redirect" red.
- X-06 route dropped: 3 tests red.
- S-38 `markStopped` removed: red.
- C-18 lower segment back to the hairline token: 2 tests red.
- `tutors-directory` removed from the perf slugs: 3 pytest cases red.
- **Live:** the G-16 mutation run through `audit.mjs` reported "G-16 /tutors FAILED: Waiting failed: 20000ms exceeded". `route-failures.json` held the entry and `check_ui_gates.py` exited 1. Restored: exit 0.
```
## F5-A block-direction masking
Return not found in the available transcripts (lane `a81c904c` ended on a session-limit notice; the task was re-dispatched in a later lane listed in this ledger).
## F5-A block-direction masking
Lane `a6d74834` (c4e7dcea), return 1/1, msg 30/30. SHA: `5ddca136` verified
```text
RED: test_tutoring_block_masking.py: family ('tutor_block','S2 upcoming') {'cancelledBy':'system'} != {'cancelledBy':'platform_admin'}; S8 'blocked' == 'tutor_unavailable'; T10 recent {'notesFrozen': False} != {'notesFrozen': True}
RED: test_booking_view.py: ('This session was cancelled.','system') != ('…by Lemely.','platform_admin'); 'completed' notesFrozen False != True
RED: test_tutor_grant_repo.py: ['active','tutor_unavailable','blocked'] != [...,'tutor_unavailable'] | test_grant_predicate_parity.py: case block='tutor_blocks_student' 'blocked' == 'tutor_unavailable'
MUTATION: family party map removed -> masking::family + booking_view (3 tests) red on c1; restored -> green
MUTATION: family reason mask removed -> same 3 tests red; restored -> green
MUTATION: tutor notesFrozen = stored flag -> masking::tutor_reads… + booking_view::…as_a_freeze red; restored -> green
MUTATION: freeze on every blocked booking (over-mask) -> booking_view::…as_a_freeze red ('completed' True != False); restored -> green
MUTATION: repo uses plain grant_status -> masking::grant_status, parity, 2 repo tests red; restored -> green
MUTATION: core window check dropped -> 3 parametrized pure cases + repo window test red; restored -> green
MUTATION: core masks every block (student's own too) -> masking S8 + parity red; restored -> green
```
## F5-A2 masking fixes
Lane `ad724c2b` (c4e7dcea), return 1/1, msg 34/34. SHA: `9b4db3a7` verified
```text
RED (against a temporary interface stub, never committed):
 test_tutoring_predicates.py:275 assert None == datetime(2026,3,1,9,0,UTC)
 test_booking_view.py:357 assert 'post_note' not in ['cancel','post_note']
 test_booking_repo.py:1688 assert None == <stored completed_at>
 test_tutoring_block_masking.py:371 {'suspended':'tutor_suspended'} != {'suspended':'tutor_unavailable'}; :476 whole-DTO diff (suspension world); :617 block world != freeze world after the window
 test_grant_predicate_parity.py:279 'tutor_suspended' == 'tutor_unavailable'
MUTATION (each red on <T>; restored with cp -> 281 passed):
 M1 core passes tutor_suspended/closed through -> block_masking ::test_a_tutor_side_end_reads_as_one_whole_grant_in_one_place, ::test_a_suspension_or_close..., parity ::test_grant_status_shown_to_the_student_equals_core
 M2 F5-A read-time mask restored -> booking_view ::test_a_block_made_inside_the_window_still_reads_as_a_freeze_after_it_closes (read_at=NOW), block_masking ::test_a_block_made_while_notes_were_open_still_reads_as_a_freeze_after_the_window
 M3 listing judged -> booking_view ::test_the_mask_outlives_whatever_follows_the_block (suspended)
 M4 no state rewind -> same test (no-show after the block)
 M5 start instant only -> same test (no-show completed after the block)
 M6 min(created_at) -> predicates ::test_active_block_since_is_the_earliest_active_rows_last_write, booking_repo ::test_rows_carry_when_the_active_block_began...
 M7 removed_at ignored -> predicates ::..._last_write, ::test_active_block_since_is_null_exactly_when_no_block_is_active
 M8 ORDER BY reads revoke_reason -> block_masking whole-grant test (position)
 M9 row reads NULL block instant -> booking_repo x2, block_masking x3
```
## F6-21 sweep instant fix
Lane `a3c7bbd7` (c4e7dcea), return 1/2, msg 21/32. SHA: none in return
```text
RED: test_tutoring_concurrency_sweeps.py: 8 failed before the fix: 3 CheckViolation ck_tutor_data_grants_revoked_after_created (grant × block/suspend/close); 3 `cancelled_at >= created_at` failed (booking × the same 3 sweeps); event order ['suspended','approved'] != ['approved','suspended']; lift removed_at 08.574945 < renewal updated_at 08.575580
RED: test_booking_repo.py / test_tutor_grant_repo.py (new `at` tests): TypeError, unexpected keyword 'at' (interface absence; needs the mutations below)
RED: test_tutoring_sweeps.py::test_sanction_stamps_every_row_with_one_instant: n/a (regression guard)
MUTATION (planned, not run, export only): (1) locked_at reads now() instead of clock_timestamp() -> the 8 new concurrency tests red; (2) booking_repo binds at=None -> booking cases + cancel_future test red; (3) grant revoke uses now() -> CheckViolation + revoke test red; (4) drop the approval-event UPDATE -> event-order test + one-instant guard red; (5) unblock stamps now() -> lift test red
```
Lane `a3c7bbd7` (c4e7dcea), return 2/2, msg 32/32. SHA: `98e7619e` verified
```text
RED: test_tutoring_concurrency_sweeps.py: 8 failed before code. 3 × CheckViolation ck_tutor_data_grants_revoked_after_created (grant × block/suspend/close); 3 × `assert cancelled_at >= created_at` (booking × the same 3); event order ['suspended','approved'] != ['approved','suspended']; lift removed_at 08.574945 < renewal updated_at 08.575580
RED: test_booking_repo.py, test_tutor_grant_repo.py (`at` keyword tests): TypeError, unexpected keyword 'at' (interface absence; proved by mutations 2 and 3)
RED: test_tutoring_sweeps.py::test_sanction_stamps_every_row_with_one_instant: n/a (regression guard; proved by mutation 4)
MUTATION: locked_at reads now() instead of clock_timestamp() -> 8 new concurrency tests red on <T>; restored -> green
MUTATION: _cancel_future binds at=None -> [block|suspended|closed]-booking + test_cancel_future_in_session_reads_the_sweeps_instant_or_now red; restored -> green
MUTATION: revoke_live_in_session stamps now() -> 3 grant cases (CheckViolation) + test_revoke_live_in_session_stamps_the_sweeps_instant_or_now red; restored -> green
MUTATION: approval-event UPDATE dropped -> 4 sanction cases + event-order test + one_instant[suspended|closed] red (7); restored -> green
MUTATION: lift stamps now() -> test_lift_stamps_follow_a_renewal_committed_after_its_transaction_began red; restored -> green
```
## F8-A evidence ceiling and PDF rescan
Lane `a165b96e` (c4e7dcea), return 1/1, msg 18/18. SHA: `34eacdba` verified
```text
RED: tests/test_tutor_evidence.py: `assert 201 == 429` (ceiling across profiles and window tests); `DID NOT RAISE EvidenceCeilingError`; race `['recorded','recorded'] == ['recorded','too_many_requests']`; statement-order test `assert 3 == 5`
RED: tests/test_evidence_files.py: `DID NOT RAISE UnsupportedEvidenceError` for the three layer cases where the action type is referenced (`type-by-reference`, `-chain`, `action-and-type-by-reference`). The `type-named` case and `test_pdf_with_a_plain_layer_is_stored_as_it_reads` are n/a (regression guard), covered by mutation 3.
MUTATION: drop global lock -> test_evidence_upload_ceiling_holds_under_concurrent_attempts_at_one_below red (`['recorded','recorded']`) on <T>; restored -> green
MUTATION: drop global count -> test_evidence_upload_ceiling_429_across_profiles red (`201 == 429`) on <T>; restored -> green
MUTATION: revert rescan alternative -> test_pdf_action_hung_off_a_layer_rejected_415 red (3 failed, 1 passed) on <T>; restored -> test_evidence_files.py 99 passed
```
## F8-B bucket owner and probes
Lane `aad30e18` (c4e7dcea), return 1/1, msg 27/27. SHA: `8d0401a6` verified
```text
RED: tests/test_tutoring_config.py: AttributeError: 'StorageSettings' object has no attribute 'gcs_project_number'
RED: tests/test_storage_gcs.py: TypeError: GcsStorageBackend.__init__() got an unexpected keyword argument 'project_number' (74 failed on pre-change code)
RED: tests/test_cli_doctor.py: StopIteration (no 'tutor_evidence_storage' check); env tests: storage.gcs_project_number extra_forbidden
RED: tests/test_deploy_evidence_bucket.py: AssertionError: deploy.yml does not set the project number | no single deploy-backend step checks the evidence bucket | bootstrap grants missing ${SA_EMAIL}
MUTATION owner check off -> test_storage_gcs::test_evidence_bucket_owned_by_another_project_is_refused 8 failed; restored -> 8 passed
MUTATION unset number passes -> ::test_unset_project_number_refuses_the_evidence_bucket 4 failed; restored -> green
MUTATION check applied to every bucket -> ::test_evidence_check_leaves_the_other_buckets_alone 3 failed; restored -> green
MUTATION ge=1 removed -> test_tutoring_config::test_gcs_project_number_must_be_a_positive_number 2 failed; restored -> green
MUTATION blank->None validator removed -> ::test_blank_gcs_project_number_reads_as_unset 2 failed; restored -> green
MUTATION deploy env_vars number line removed -> test_deploy_evidence_bucket::test_deploy_sets_the_project_number_for_both_environments red; restored -> green
MUTATION regex [0-9]+ -> [^/]+ -> ::test_deploy_stops_on_a_provider_without_a_project_number 2 failed; restored -> green
MUTATION deploy-check owner test off / privacy test reduced to the uniform check -> ::test_deploy_checks_the_evidence_bucket_is_private_and_ours 4 failed each; restored -> 14 passed
MUTATION deployer grant -> runtime account -> ::test_gcp_bootstrap_creates_private_evidence_bucket red; restored -> green
MUTATION doctor record line removed -> tests/test_cli_doctor.py 6 failed; restored -> 40 passed
MUTATION doctor reads the bucket but skips the owner/privacy check -> test_storage_gcs::test_doctor_evidence_check_reports_the_privacy_and_owner_result 2 failed; restored -> green
MUTATION doctor unset-number branch off -> ::test_doctor_evidence_check_refuses_offline_misconfiguration 1 failed; restored -> green
```
## F9-D1 tutor not redirected to first-class
Lane `a2905fcb` (c4e7dcea), return 1/1, msg 3/3. SHA: `12553735` verified
```text
RED: teacherRedirect.test.ts: "/teacher/tutoring: expected false to be true" (helper stubbed to false; 4 of 8 red). tutorStudentView.test.ts: T-19 "expected ... to contain 'Students share their progress with tu...'" (3 red; the fourth case was my own test error on the 404 not_found page, which has no retry, fixed in the test).
MUTATION:
- gate redirects tutoring paths again (skip line removed from teacherFirstClassRedirect) -> teacherRedirect.test.ts "does not send a zero-class teacher away from any tutoring screen" and "the gate function consults the helper before it can return the redirect" red on T; restored -> green
- prefix match without the segment boundary (startsWith(ROOT)) -> "is false for a look-alike that only shares the prefix" and "still sends a zero-class teacher from every other route, look-alikes included" red; restored -> green
- isNoTutorProfile ignoring status 404 -> "isNoTutorProfile is only the 404 with that code" and both "keeps the failure state for every other error" red; restored -> green
- T-19 stops showing the onboarding state -> "T-19 shows the onboarding state with a link to the profile, not the error" red; restored -> green
```
## F9-D2 parent notice to self
Lane `ae0c9d23` (c4e7dcea), return 1/1, msg 8/8. SHA: none in return
```text
RED: n/a. Repro on a throwaway tutoring_database() through the real seams, run with `PYTHONPATH=$WT .venv/bin/python -P .omc/scratch-d2/repro.py`:
 1) seed path, ParentLinkService.link_in_session(seeded, child) as in scripts/seed_e2e.py:2716:
 after seed link: inbox: [] outbox: []
 2) InviteService.redeem(fresh, <child's parent code>) + redeem_notices/send_after_commit:
 after fresh parent redeems: inbox: [('SEEDED','parent_link','A parent was added')] outbox: [('SEEDED','parent_linked')]
DIAGNOSIS: the seeded parent is never told about their own link. The new parent's own link creates no notice:
 link_in_session reads `linked` before inserting, and the recipients are only the parents already linked.
 The notice comes from parent-journey.spec.ts test (a): a fresh parent redeems `declining.parentInviteCode`.
 That is the same child the seeded parent is linked to (seed_e2e.py:3092 linkedStudent "declining").
 The seeded parent is therefore an existing parent being told ANOTHER parent was added.
 The fresh parent (the actor) gets nothing.
```
## F30-1 evidence bucket
Lane `a66f6ddf` (c4e7dcea), return 1/1, msg 49/49. SHA: `5d4ba57f` verified
```text
RED: test_deploy_evidence_bucket.py: "deploy.yml does not set the evidence bucket" / "gcp-bootstrap.sh names no evidence bucket" | test_storage_gcs.py: TypeError, no `tutor_evidence_bucket` parameter (missing interface; the MUTATION lines below are the proof) | test_tutoring_config.py::test_local_backend_keeps_default_evidence_bucket: n/a (regression guard)
MUTATION: default-name refusal removed -> test_gcs_backend_refuses_default_evidence_bucket[3] red; restored -> green
MUTATION: public-access-prevention test dropped -> test_evidence_bucket_public_access_prevention_enforced 12 red (4 ops × unspecified/inherited/missing); restored -> green
MUTATION: uniform-access test dropped -> 4 red (enforced, uniform off); restored -> green
MUTATION: guard removed from create_signed_url (the A2 path) -> 5 red; restored -> green
MUTATION: failed check remembered -> test_unreadable_evidence_bucket_fails_closed_and_is_checked_again[NotFound] red; restored -> green
MUTATION: every bucket checked -> test_evidence_check_leaves_the_other_buckets_alone red; restored -> green
MUTATION: deploy.yml gives both environments one name -> test_deploy_sets_per_environment_tutor_evidence_bucket red; restored -> green
MUTATION: bootstrap name differs from deploy.yml -> the deploy test red (cross-check); restored -> green
MUTATION: bootstrap create without --public-access-prevention / evidence bucket left out of the loop / legacyBucketReader swapped -> test_gcp_bootstrap_creates_private_evidence_bucket red (3 separate runs); restored -> green
MUTATION: local backend refuses the default (storage_local.py, in the export only, owned by no lane) -> test_local_backend_keeps_default_evidence_bucket red; restored from HEAD -> green
```
## F30-2 quotas, F30-4 granted day
Lane `a6518bd1` (c4e7dcea), return 1/1, msg 22/22. SHA: `eb1b1064` verified
```text
RED: test_tutoring_concurrency_bookings.py: `Failed: the second transaction never queued on the advisory key 'tutoring_cancel:…'` (×2) and `'tutoring_booking_create:…'`
RED: test_booking_repo.py::test_cancel_and_create_take_the_actor_quota_lock_first: `assert None is not None` (the first statement was the `_locate` SELECT)
RED: test_web_tutor_students.py: `fullmatch('\d{4}-\d{2}-\d{2}', '2026-10-24T22:30:00+00:00')` is None (the new privacy test, and the updated test_t20_success_shape)
RED: test_student_detail_view.py: n/a (new helper; the only pre-code failure was an ImportError), proved by MUTATION below
RED: tutorStudentView.test.ts: n/a (regression guard; it passes before code), proved by MUTATION below
MUTATION: cancel lock removed -> both cancel races (two tutors; tutor with two students) + quota_lock_first red on <T>; restored -> green
MUTATION: create lock removed -> parent_create_quota_two_children + quota_lock_first red; restored -> green
MUTATION: both locks removed and the wait helper made non-waiting -> the second cancel or create commits (`second.error` is None, so 11 in 24 h, as F30-2 reproduced); restored
MUTATION: T19 grantedAt back to `iso_instant` -> privacy test red; same for T20 -> privacy + success_shape red; restored -> green
MUTATION: `tutor_zone_day` cutting in UTC -> privacy test (`'2026-10-24' != '2026-10-25'`) + helper test red; restored
MUTATION: `dayLabel` re-cutting a bare day as UTC midnight -> new vitest red; restored -> 54/54
```
## F30-3/5 evidence PDFs and quota
Lane `ad3ca7e3` (c4e7dcea), return 1/1, msg 42/42. SHA: `fa1b29a5` verified
```text
RED: tests/test_evidence_files.py: test_evidence_pdf_widget_actions_refused[submit-form] `assert not doc.is_form_pdf` (got 1); 10 of 11 cases red; [names-javascript] n/a (regression guard: rewrite never carried the catalog); [benign-visible-link] Annots 'array' != 'null'; plain-pages, subset-font-name, still_interactive_after_flattening, flattened_over_the_cap n/a (regression guard), see MUTATION
RED: tests/test_tutor_evidence.py: test_t6_stores_a_form_pdf_flattened_with_no_action_left `assert not doc.is_form_pdf` (got 1)
MUTATION: no strip (drop _strip_interactive) -> widget_actions_refused + benign-link: 11 failed on c2; restored -> 14 passed
MUTATION: no post-flatten scan (drop _refuse_interactive) -> test_pdf_still_interactive_after_flattening_rejected_415 red (DID NOT RAISE); restored -> green
MUTATION: no bake (deletions kept) -> widget_actions_refused: 7 widget cases red (caption text "Verify" lost); restored -> 11 passed
MUTATION: no pre-flatten refusal of AA/JS/Launch/EF/XFA -> test_pdf_whose_kept_annotations_carry_actions_or_files_rejected_415: 5/5 red (DID NOT RAISE); restored -> green
MUTATION: no size check on flattened bytes -> test_pdf_flattened_over_the_cap_rejected_413 red; restored -> green
```
## F30-5 evidence upload quota
Lane `a02215f7` (c4e7dcea), return 1/1, msg 50/50. SHA: `fbd4f0ba` verified
```text
RED: test_tutor_evidence.py::test_evidence_upload_quota_429: assert [0, 0, 0, …] == [1, 2, 3, …] (no attempt committed before the check);
 ::test_evidence_upload_quota_is_per_profile and ::…_window_is_elapsed_time: assert 201 == 429;
 ::…_holds_under_concurrent_attempts_at_nineteen, ::test_evidence_upload_attempt_lock_is_the_first_statement: n/a (regression guard, see MUTATION)
RED: test_db_schema.py::test_0043_merge_heads…: assert ['0050_tutoring_safety'] == ['0051_tutor_evidence_uploads']; ::test_all_expected_tables_registered: set mismatch
RED: test_db_tutoring_schema.py::test_orm_registers_every_spec_table: set mismatch; ::test_create_all_and_migrations_build_identical_tutoring_schemas: "columns" (model before migration)
RED: test_migration_tutor_evidence_uploads.py::test_constraints_present_by_name: assert set() == {'fk_tutor_ev…'} (model before migration)
MUTATION: drop _lock_upload_attempts -> …concurrent_attempts_at_nineteen red (['recorded','recorded']) + lock_is_the_first_statement red (2 == 3); restored -> green
MUTATION: count tutor_evidence_files instead of tutor_evidence_uploads -> test_evidence_upload_quota_429 red (201 == 429 after upload+delete loops); restored -> green
MUTATION: record the attempt after the worker check -> test_evidence_upload_quota_429 red ([0, 0, 1, …]: the 415 went uncounted); restored -> green
MUTATION: drop the window predicate -> …_window_is_elapsed_time red (429 == 201); restored -> green (34 passed on the restored export)
```

## Summary table

| Task / lane | has RED or MUTATION lines | MUTATION lines | test files named |
|---|---|---|---|
| T00 execution tooling | yes | 11 | `tests/tutoring_app.py` (from FILES; ACCEPTANCE names none) |
| T01 schema migrations models | yes | 15 | `tests/test_db_schema.py`, `tests/test_db_tutoring_schema.py`, `tests/test_me_router.py`, `tests/test_notification_prefs_repo.py`, `tests/test_tutoring_predicates.py`, `tests/test_tutoring_predicates_single_source.py` (from FILES; ACCEPTANCE names none) |
| T02 pure rules A | yes | 17 | `tests/test_core_contact_patterns.py`, `tests/test_core_keyset.py`, `tests/test_core_tutor_directory.py`, `tests/test_core_tutor_ratings.py` |
| T03 booking state machine | yes | 11 | `tests/test_core_booking.py`, `tests/test_core_booking_slots.py` |
| T04 API contract DTOs | yes | 11 | `tests/test_schemas_tutoring.py` |
| T05 grant validity and outcome stats | yes | 13 | `tests/test_core_tutor_grants.py`, `tests/test_core_tutor_outcomes.py`, `tests/test_tutoring_cross_pins.py` (from FILES; ACCEPTANCE names none) |
| T06 profiles directory route classes | yes | 6 | `tests/test_tutor_directory_repo.py`, `tests/test_tutor_profile_repo.py`, `tests/test_tutoring_http.py`, `tests/test_web_tutor.py`, `tests/test_web_tutoring_authz_profiles.py`, `tests/test_web_tutoring_public.py`, `tests/tutoring_db.py` (from FILES; ACCEPTANCE names none) |
| T07 notifications email outbox | yes | 10 | `tests/test_email_outbox_repo.py`, `tests/test_migration_tutoring_enums.py`, `tests/test_notify_email.py`, `tests/test_scheduled_notifications.py`, `tests/test_tutoring_email.py`, `tests/test_tutoring_notify.py` (from FILES; ACCEPTANCE names none) |
| T08 edge indexing and cache | yes | 13 | `tests/test_deploy_headers.py`, `web/tests/unit/support/workersRuntime.d.ts`, `web/tests/unit/workerTutorRobots.test.ts` (from FILES; ACCEPTANCE names none) |
| T09 existing routes row 14 | yes | 5 | `tests/test_class_side_door.py`, `tests/test_email_verified_first_timestamp.py`, `tests/test_parent_link_integrity.py` (from FILES; ACCEPTANCE names none) |
| T09 review fixes | yes | 6 | `tests/auth_fakes.py`, `tests/test_class_side_door.py`, `tests/test_email_verified_first_timestamp.py`, `tests/test_parent_link_integrity.py` (from FILES; ACCEPTANCE names none) |
| T10 admin approval and evidence | yes | 10 | `tests/storage_fakes.py`, `tests/test_evidence_files.py`, `tests/test_storage_gcs.py`, `tests/test_storage_local.py`, `tests/test_tutor_approval_repo.py`, `tests/test_tutor_evidence.py`, `tests/test_web_admin_tutoring.py`, `tests/test_web_tutoring_authz_admin.py` (from FILES; ACCEPTANCE names none) |
| T10 review fixes | yes | 10 | `tests/storage_fakes.py` (from FILES; ACCEPTANCE names none) |
| T11 web API hooks | yes | 12 | `tests/unit/persistAllowlist.test.ts`, `tests/unit/tutoringApiErrors.test.ts`, `tests/unit/tutoringQueryKeys.test.ts`, `web/tests/unit/tutoringApiErrors.test.ts`, `web/tests/unit/tutoringQueryKeys.test.ts` (from FILES; ACCEPTANCE names none) |
| T12 review fixes | yes | 7 | none named (from FILES; ACCEPTANCE names none) |
| T12 reviews and moderation | yes | 17 | `tests/test_tutor_review_repo.py`, `tests/test_tutoring_cli.py`, `tests/test_tutoring_concurrency_reviews.py`, `tests/test_web_tutor_reviews.py`, `tests/test_web_tutoring_authz_reviews.py` |
| T13 booking service | yes | 5 | `tests/test_booking_predicates_parity.py`, `tests/test_booking_repo.py`, `tests/test_booking_view.py`, `tests/test_tutoring_concurrency_bookings.py` (from FILES; ACCEPTANCE names none) |
| T13 review fixes | yes | 9 | `tests/test_booking_predicates_parity.py`, `tests/test_booking_repo.py`, `tests/test_booking_view.py`, `tests/test_tutoring_concurrency_bookings.py`, `web/tests/unit/tutoringApiErrors.test.ts` (from FILES; ACCEPTANCE names none) |
| T14 grants audit tutor view | yes | 4 | none named (from FILES; ACCEPTANCE names none) |
| T14 review fixes | yes | 9 | none named (from FILES; ACCEPTANCE names none) |
| T15 UI components C-17..C-24 | yes | 9 | none named (from FILES; ACCEPTANCE names none) |
| T15 review fixes | yes | 0 | none named (from FILES; ACCEPTANCE names none) |
| T16 tutoring copy-lint rule | no | 0 | return not found |
| T17 family booking routes | yes | 7 | none named (from FILES; ACCEPTANCE names none) |
| F5-17 T17 review fixes | no | 0 | return not found |
| F5-17 T17 review fixes | yes | 6 | `tests/test_web_parent_bookings.py`, `tests/test_web_student_bookings.py`, `tests/test_web_tutoring_authz_bookings_family.py`, `tests/test_web_tutoring_booking.py` (from FILES; ACCEPTANCE names none) |
| T18 tutor booking routes | yes | 5 | `tests/test_booking_repo.py`, `tests/test_web_tutor_bookings.py`, `tests/test_web_tutoring_authz_bookings_tutor.py` |
| F5-T test hardening T18 T19 T20 | no | 0 | return not found |
| F5-T test hardening T18 T19 T20 | yes | 9 | `tests/test_outcome_eligibility_parity.py`, `tests/test_tutor_outcomes_repo.py`, `tests/test_web_parent_tutor_access.py`, `tests/test_web_student_tutoring_settings.py`, `tests/test_web_tutor_bookings.py`, `tests/test_web_tutoring_authz_bookings_tutor.py`, `tests/test_web_tutoring_authz_parent_sharing.py` (from FILES; ACCEPTANCE names none) |
| T19 outcome figures | yes | 7 | `tests/test_outcome_eligibility_parity.py`, `tests/test_tutor_outcomes_repo.py`, `tests/test_tutoring_predicates_single_source.py`, `tests/test_web_tutoring_outcomes.py` |
| F30-6 T19 cursor leak | yes | 4 | `tests/test_tutor_grant_repo.py`, `tests/test_web_tutor_students.py`, `tests/test_web_tutoring_authz_grants.py` (from FILES; ACCEPTANCE names none) |
| T20 settings and parent views | yes | 4 | `tests/test_web_parent_tutor_access.py`, `tests/test_web_student_tutoring_settings.py`, `tests/test_web_tutoring_authz_parent_sharing.py` (from FILES; ACCEPTANCE names none) |
| T21 blocks and sweeps | yes | 11 | `tests/test_tutoring_blocks_repo.py`, `tests/test_tutoring_concurrency_sweeps.py`, `tests/test_tutoring_sweeps.py`, `tests/test_web_admin_tutor_sanctions.py`, `tests/test_web_tutoring_authz_blocks.py`, `tests/test_web_tutoring_blocks.py` (from FILES; ACCEPTANCE names none) |
| T22 discovery screens | yes | 3 | none named (from FILES; ACCEPTANCE names none) |
| F6-22 T22 review fixes | yes | 3 | none named (from FILES; ACCEPTANCE names none) |
| T23 student session screens | yes | 12 | `tests/unit/tutoringAccessView.test.ts`, `tests/unit/tutoringSessionView.test.ts` |
| F6-23 T23 review fixes | yes | 14 | `tests/unit/tutoringAccessView.test.ts`, `tests/unit/tutoringSessionScreens.test.ts`, `tests/unit/tutoringSessionView.test.ts` |
| T24 teacher tutoring screens | yes | 15 | none named (from FILES; ACCEPTANCE names none) |
| F6-24 T24 review fixes | yes | 3 | none named (from FILES; ACCEPTANCE names none) |
| T25 reports and cross-cutting | yes | 9 | `tests/test_tutoring_cross_cutting.py`, `tests/test_tutoring_reports_repo.py`, `tests/test_web_admin_tutoring_reports.py`, `tests/test_web_tutoring_authz_reports.py`, `tests/test_web_tutoring_reports.py` (from FILES; ACCEPTANCE names none) |
| F7-25 T25 review fixes | yes | 7 | none named (from FILES; ACCEPTANCE names none) |
| T26 tutor-student screens | yes | 5 | `web/tests/unit/tutorStudentView.test.ts` (from FILES; ACCEPTANCE names none) |
| F7-26 T26 review fixes | yes | 7 | `tests/unit/tutorStudentView.test.ts` |
| T27 parent screens | yes | 14 | `tests/unit/parentTutoring.test.ts` |
| F7-27 T27 plus shared copy fixes | yes | 10 | none named (from FILES; ACCEPTANCE names none) |
| T28 admin screens | yes | 9 | `web/tests/unit/adminTutoring.test.ts` (from FILES; ACCEPTANCE names none) |
| F7-28 T28 review fixes | yes | 11 | `tests/unit/adminTutoring.test.ts` |
| T29 e2e seed data | yes | 6 | `tests/test_seed.py`, `tests/test_seed_e2e.py` |
| T31 Phase 4 docs | yes | 2 | `web/tests/unit/dataHandling.test.ts` (from FILES; ACCEPTANCE names none) |
| T32 e2e journeys (live) | yes | 9 | `tests/test_seed_e2e.py` (from FILES; ACCEPTANCE names none) |
| T33 UI QA (live) | yes | 7 | `tests/test_check_ui_gates.py` |
| F5-A block-direction masking | no | 0 | return not found |
| F5-A block-direction masking | yes | 7 | `tests/test_booking_view.py`, `tests/test_grant_predicate_parity.py`, `tests/test_tutor_grant_repo.py`, `tests/test_tutoring_block_masking.py` (from FILES; ACCEPTANCE names none) |
| F5-A2 masking fixes | yes | 9 | `tests/test_booking_repo.py`, `tests/test_booking_view.py`, `tests/test_grant_predicate_parity.py`, `tests/test_tutoring_block_masking.py`, `tests/test_tutoring_predicates.py` (from FILES; ACCEPTANCE names none) |
| F6-21 sweep instant fix | yes | 6 | `tests/test_booking_repo.py`, `tests/test_tutor_grant_repo.py`, `tests/test_tutoring_concurrency_sweeps.py`, `tests/test_tutoring_sweeps.py` (from FILES; ACCEPTANCE names none) |
| F8-A evidence ceiling and PDF rescan | yes | 3 | `tests/test_evidence_files.py`, `tests/test_tutor_evidence.py` (from FILES; ACCEPTANCE names none) |
| F8-B bucket owner and probes | yes | 11 | `tests/test_cli_doctor.py`, `tests/test_deploy_evidence_bucket.py`, `tests/test_storage_gcs.py`, `tests/test_tutoring_config.py` (from FILES; ACCEPTANCE names none) |
| F9-D1 tutor not redirected to first-class | yes | 4 | `web/tests/unit/teacherRedirect.test.ts`, `web/tests/unit/tutorStudentView.test.ts` (from FILES; ACCEPTANCE names none) |
| F9-D2 parent notice to self | yes | 0 | none named (from FILES; ACCEPTANCE names none) |
| F30-1 evidence bucket | yes | 10 | `tests/test_deploy_evidence_bucket.py`, `tests/test_storage_gcs.py`, `tests/test_tutoring_config.py` (from FILES; ACCEPTANCE names none) |
| F30-2 quotas, F30-4 granted day | yes | 6 | `tests/test_booking_repo.py`, `tests/test_student_detail_view.py`, `tests/test_tutoring_concurrency_bookings.py`, `tests/test_web_tutor_students.py`, `web/tests/unit/tutorStudentView.test.ts` (from FILES; ACCEPTANCE names none) |
| F30-3/5 evidence PDFs and quota | yes | 5 | `tests/test_evidence_files.py`, `tests/test_tutor_evidence.py` (from FILES; ACCEPTANCE names none) |
| F30-5 evidence upload quota | yes | 4 | `tests/test_db_schema.py`, `tests/test_db_tutoring_schema.py`, `tests/test_migration_tutor_evidence_uploads.py`, `tests/test_tutor_evidence.py` (from FILES; ACCEPTANCE names none) |
