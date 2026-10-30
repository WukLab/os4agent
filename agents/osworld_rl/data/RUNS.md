| run | start (PDT) | system | tasks | replay of | flags | rollouts | reward>0 | wall min |
|---|---|---|---|---|---|---|---|---|
| ab30_A | 10-30 03:02 | tfork | grpo16.json | rec30_shot | max_steps=30 release_copies=1 | 32 | 14 | 15.9 |
| ab30_B | 10-30 03:02 | tfork | grpo16.json | rec30_shot | max_steps=30 release_copies=1 spec=tage spec_exec=1 spec_max_forks=64 spec_slow=1 spec_inplace=1 | 32 | 14 | 15.3 |
| aenv_chrome_rerun | 10-26 12:23 | aenv | aenv_chrome2.json |  |  | 16 | 0 | 6.5 |
| aenv_failed_rerun | 10-26 12:05 | aenv | aenv_failed.json |  |  | 8 | 0 | 7.1 |
| aenv_nested4 | 10-27 14:13 | aenv | nested4.json | rec32v2_tfork | base_fork=1 | 32 | 1 | 7.8 |
| aenv_sample | 10-26 11:13 | aenv | aenv_sample.json |  |  | 24 | 2 | 8.7 |
| bf4_tfork_base | 10-26 14:24 | tfork | basefork4.json |  | max_steps=5 base_fork=1 | 32 | 0 | 17.1 |
| bf4_tfork_plain | 10-26 14:32 | tfork | basefork4.json |  | max_steps=5 | 32 | 0 | 5.4 |
| cap30_shot | 10-30 02:16 | tfork | long8.json |  | max_steps=30 release_copies=1 | 16 | 4 | 11.6 |
| diff15_shot | 10-30 01:22 | tfork | diff15.json |  | release_copies=1 | 45 | 10 | 12.7 |
| drag_pivot | 10-30 01:43 | tfork | pivot1.json | diff15_shot | max_steps=5 release_copies=1 replay_latency=0.0 | 1 | 0 | 1.8 |
| fc_S16 | 10-29 11:06 | tfork | pfx_test_tasks.json | grpo_tfork16_e0 | fork_concurrency=16 release_copies=1 replay_latency=0.25 prefix_cache=pfx_fc16 overlay_rootfs=0 | 16 | 10 | 18.0 |
| fc_S8 | 10-29 10:49 | tfork | pfx_test_tasks.json | grpo_tfork16_e0 | fork_concurrency=8 release_copies=1 replay_latency=0.25 prefix_cache=pfx_fc8 overlay_rootfs=0 | 16 | 11 | 17.7 |
| fix16_shot | 10-30 01:50 | tfork | grpo16.json |  | release_copies=1 | 32 | 9 | 12.5 |
| grpo_tfork16_e0 | 10-28 17:50 | tfork | grpo_batch32v2.json |  | release_copies=1 | 128 | 11 | 12.6 |
| grpo_tfork16_e1 | 10-28 18:04 | tfork | grpo_batch32v2.json |  | release_copies=1 | 128 | 10 | 12.1 |
| grpo_tfork16_e2 | 10-28 18:18 | tfork | grpo_batch32v2.json |  | release_copies=1 | 128 | 13 | 11.6 |
| grpo_tfork16_e3 | 10-28 18:31 | tfork | grpo_batch32v2.json |  | release_copies=1 | 128 | 15 | 11.4 |
| grpo_tfork16_e4 | 10-28 18:44 | tfork | grpo_batch32v2.json |  | release_copies=1 | 128 | 14 | 12.1 |
| grpo_tfork16_e5 | 10-28 18:58 | tfork | grpo_batch32v2.json |  | release_copies=1 | 128 | 15 | 11.4 |
| grpo_tfork16_e6 | 10-28 19:11 | tfork | grpo_batch32v2.json |  | release_copies=1 | 128 | 13 | 11.9 |
| grpo_tfork16_e7 | 10-28 19:25 | tfork | grpo_batch32v2.json |  | release_copies=1 | 128 | 11 | 11.3 |
| grpo_tfork16_e8 | 10-28 19:38 | tfork | grpo_batch32v2.json |  | release_copies=1 | 128 | 15 | 11.4 |
| grpo_tfork16_e9 | 10-28 19:51 | tfork | grpo_batch32v2.json |  | release_copies=1 | 128 | 11 | 13.4 |
| grpo_tfork16_pfx_e0 | 10-28 23:26 | tfork | grpo_batch32v2.json |  | release_copies=1 prefix_cache=pfx_grpo overlay_rootfs=0 | 128 | 10 | 16.5 |
| grpo_tfork16_pfx_e1 | 10-28 23:44 | tfork | grpo_batch32v2.json |  | release_copies=1 prefix_cache=pfx_grpo overlay_rootfs=0 | 128 | 12 | 15.2 |
| grpo_tfork16_pfx_e2 | 10-29 00:01 | tfork | grpo_batch32v2.json |  | release_copies=1 prefix_cache=pfx_grpo overlay_rootfs=0 | 128 | 14 | 15.8 |
| grpo_tfork16_pfx_e3 | 10-29 00:19 | tfork | grpo_batch32v2.json |  | release_copies=1 prefix_cache=pfx_grpo overlay_rootfs=0 | 128 | 11 | 16.1 |
| grpo_tfork16_pfx_e4 | 10-29 00:37 | tfork | grpo_batch32v2.json |  | release_copies=1 prefix_cache=pfx_grpo overlay_rootfs=0 | 128 | 12 | 18.3 |
| grpo_think_reg_e0 | 10-29 17:50 | tfork | grpo_batch32v2.json |  | release_copies=1 | 128 | 11 | 29.4 |
| grpo_think_reg_e1 | 10-29 18:20 | tfork | grpo_batch32v2.json |  | release_copies=1 | 128 | 11 | 50.5 |
| grpo_think_reg_e2 | 10-29 21:05 | tfork | grpo_batch32v2.json |  | release_copies=1 | 128 | 12 | 21.4 |
| grpo_think_spec_e0 | 10-29 19:13 | tfork | grpo_batch32v2.json |  | release_copies=1 spec_exec=2 spec_max_forks=10 | 128 | 12 | 30.2 |
| grpo_think_spec_e1 | 10-29 19:45 | tfork | grpo_batch32v2.json |  | release_copies=1 spec_exec=2 spec_max_forks=10 | 128 | 14 | 50.9 |
| grpo_think_spec_e2 | 10-29 21:27 | tfork | grpo_batch32v2.json |  | release_copies=1 spec_exec=2 spec_max_forks=10 | 21 | 14 | 7.5 |
| grpo_think_specsame_e2 | 10-29 21:37 | tfork | grpo_batch32v2.json |  | release_copies=1 spec_exec=2 spec_max_forks=10 | 128 | 12 | 15.6 |
| home_vlc | 10-30 01:36 | tfork | vlc_rec.json | diff15_shot | release_copies=1 replay_latency=0.0 | 1 | 1 | 2.0 |
| incA_shot | 10-30 00:32 | tfork | incA.json |  | release_copies=1 | 15 | 3 | 8.0 |
| inplace_e2 | 10-29 22:38 | tfork | grpo_batch32v2.json |  | release_copies=1 spec_exec=1 spec_max_forks=10 spec_inplace=1 | 128 | 13 | 16.0 |
| ld_nocache_ov0 | 10-29 02:25 | tfork | grpo_batch32v2.json | grpo_tfork16_pfx_e1 | release_copies=1 overlay_rootfs=0 | 50 | 12 | 6.1 |
| ld_nocache_ov1 | 10-29 02:12 | tfork | grpo_batch32v2.json | grpo_tfork16_pfx_e1 | release_copies=1 | 128 | 12 | 12.5 |
| lo3_shot | 10-30 01:13 | tfork | lo3.json |  | release_copies=1 | 9 | 1 | 9.2 |
| osw_aenv29 | 10-26 10:15 | aenv | grpo_batch29.json |  |  | 216 | 0 | 35.3 |
| osw_aenv29_crashed_emfile | 10-26 09:03 | aenv | grpo_batch29.json |  |  | 50 | 0 | 8.9 |
| osw_aenv29_par8 | 10-26 11:53 | aenv | grpo_batch29.json |  | parallel=8 | 87 | 2 | 10.6 |
| osw_aenv32_capped | 10-26 07:50 | aenv | grpo_batch32.json |  |  | 51 | 0 | 9.4 |
| osw_criu29 | 10-26 09:13 | criu | grpo_batch29.json |  |  | 224 | 8 | 36.7 |
| osw_criu32_capped | 10-26 08:00 | criu | grpo_batch32.json |  |  | 248 | 10 | 50.3 |
| osw_criu32_e0 | 10-25 22:12 | criu | grpo_batch32.json |  |  | 137 | 10 | 19.9 |
| osw_criu32_once | 10-25 22:34 | criu | grpo_batch32.json |  |  | 208 | 7 | 52.2 |
| osw_criu_e0 | 10-25 21:35 | criu | grpo_batch.json |  |  | 56 | 9 | 13.0 |
| osw_criu_e1 | 10-25 21:53 | criu | grpo_batch.json |  |  | 72 | 9 | 13.7 |
| osw_criu_e2 | 10-25 22:10 | criu | grpo_batch.json |  |  | 0 | 0 | 0.7 |
| osw_tfork29 | 10-26 09:50 | tfork | grpo_batch29.json |  |  | 208 | 11 | 25.3 |
| osw_tfork32_capped | 10-26 08:51 | tfork | grpo_batch32.json |  |  | 92 | 1 | 9.3 |
| osw_tfork32_once | 10-25 23:26 | tfork | grpo_batch32.json |  |  | 88 | 12 | 41.3 |
| pf30_A | 10-30 03:24 | tfork | grpo16.json | rec30_shot | max_steps=30 release_copies=1 | 3 | 3 | 2.7 |
| pf30_P | 10-30 03:24 | tfork | grpo16.json | rec30_shot | max_steps=30 release_copies=1 spec=tage spec_exec=1 spec_max_forks=64 spec_slow=1 spec_prefork=1 | 32 | 14 | 15.5 |
| pf30b_P | 10-30 03:40 | tfork | grpo16.json | rec30_shot | max_steps=30 release_copies=1 spec=tage spec_exec=1 spec_max_forks=16 spec_slow=1 spec_prefork=1 | 10 | 9 | 3.6 |
| pf30c_P | 10-30 03:44 | tfork | grpo16.json | rec30_shot | max_steps=30 release_copies=1 spec=tage spec_exec=1 spec_max_forks=16 spec_slow=1 spec_prefork=1 | 32 | 14 | 14.8 |
| pf30d_P | 10-30 03:59 | tfork | grpo16.json | rec30_shot | max_steps=30 release_copies=1 spec=tage spec_exec=1 spec_max_forks=24 spec_slow=1 spec_prefork=1 | 32 | 14 | 14.8 |
| pfx_A | 10-28 22:00 | tfork | pfx_test_tasks.json | grpo_tfork16_e0 | parallel=1 fork_concurrency=2 release_copies=1 | 16 | 11 | 7.8 |
| pfx_A0 | 10-28 22:40 | tfork | pfx_test_tasks.json | grpo_tfork16_e0 | parallel=1 fork_concurrency=2 release_copies=1 overlay_rootfs=0 | 16 | 11 | 8.0 |
| pfx_B | 10-28 22:24 | tfork | pfx_test_tasks.json | grpo_tfork16_e0 | parallel=1 fork_concurrency=2 release_copies=1 prefix_cache=pfx_cache overlay_rootfs=0 | 16 | 11 | 8.4 |
| pfx_C | 10-28 22:33 | tfork | pfx_test_tasks.json | grpo_tfork16_e0 | parallel=1 fork_concurrency=2 release_copies=1 prefix_cache=pfx_cache overlay_rootfs=0 | 16 | 11 | 7.5 |
| pfx_C_tmpl | 10-29 02:03 | tfork | pfx_test_tasks.json | grpo_tfork16_e0 | fork_concurrency=2 release_copies=1 prefix_cache=pfx_cache overlay_rootfs=0 | 16 | 11 | 9.2 |
| prof_criu_spec_off | 10-25 17:52 | criu | grpo_batch.json |  |  | 72 | 0 | 56.7 |
| prof_criu_spec_tage | 10-25 18:49 | criu | grpo_batch.json |  | spec=tage | 72 | 0 | 54.2 |
| qv_A | 10-29 10:18 | tfork | pfx_test_tasks.json | grpo_tfork16_e0 | release_copies=1 replay_latency=0.25 | 16 | 9 | 3.7 |
| qv_R | 10-29 10:29 | tfork | pfx_test_tasks.json | grpo_tfork16_e0 | release_copies=1 replay_latency=0.25 prefix_cache=pfx_qv | 16 | 11 | 1.8 |
| qv_S | 10-29 10:22 | tfork | pfx_test_tasks.json | grpo_tfork16_e0 | release_copies=1 replay_latency=0.25 prefix_cache=pfx_qv overlay_rootfs=0 | 16 | 10 | 6.8 |
| r128_A | 10-30 04:41 | tfork | grpo16.json | rec128_shot | max_steps=20 release_copies=1 | 128 | 52 | 18.4 |
| r128_P | 10-30 05:00 | tfork | grpo16.json | rec128_shot | max_steps=20 release_copies=1 spec=tage spec_exec=1 spec_max_forks=24 spec_slow=1 spec_prefork=1 | 128 | 52 | 18.2 |
| r128_P2 | 10-30 05:18 | tfork | grpo16.json | rec128_shot | max_steps=20 release_copies=1 spec=tage spec_exec=1 spec_max_forks=24 spec_slow=1 spec_prefork=1 | 128 | 52 | 18.3 |
| r128_P3 | 10-30 05:41 | tfork | grpo16.json | rec128_shot | max_steps=20 release_copies=1 spec=tage spec_exec=1 spec_max_forks=48 spec_slow=1 spec_prefork=1 | 128 | 52 | 18.1 |
| r128_aenv | 10-30 06:55 | aenv | grpo16.json | rec128_shot | max_steps=20 release_copies=1 | 120 | 26 | 21.2 |
| r128_criu | 10-30 06:07 | criu | grpo16.json | rec128_shot | max_steps=20 release_copies=1 | 128 | 49 | 23.8 |
| r128e1_TREE | 10-30 08:53 | tfork | grpo16.json | rec128_shot | max_steps=20 release_copies=1 tree_cache=traces/tree_cache_p2 overlay_rootfs=0 | 0 | 0 | 0.0 |
| r128e2_P2 | 10-30 07:34 | tfork | grpo16.json | rec128e2_shot | max_steps=20 release_copies=1 spec=tage spec_exec=1 spec_max_forks=24 spec_slow=1 spec_prefork=1 | 128 | 45 | 19.5 |
| r128e2_PS | 10-30 09:03 | tfork | grpo16.json | rec128e2_shot | max_steps=20 release_copies=1 spec=tage spec_exec=1 spec_max_forks=24 spec_slow=1 spec_prefork=1 screen_cache=1 | 128 | 45 | 20.3 |
| r128e2_PS2 | 10-30 09:24 | tfork | grpo16.json | rec128e2_shot | max_steps=20 release_copies=1 spec=tage spec_exec=1 spec_max_forks=24 spec_slow=1 spec_prefork=1 screen_cache=1 | 0 | 0 | 0.7 |
| r128e2_PS3_aborted_a11y | 10-30 10:20 | tfork | grpo16.json | rec128e2_shot | max_steps=20 release_copies=1 spec=tage spec_exec=1 spec_max_forks=24 spec_slow=1 spec_prefork=1 screen_cache=1 | 32 | 21 | 4.7 |
| r128e2_SC | 10-30 08:21 | tfork | grpo16.json | rec128e2_shot | max_steps=20 release_copies=1 screen_cache=1 | 109 | 43 | 14.5 |
| r128e2_SC2 | 10-30 08:36 | tfork | grpo16.json | rec128e2_shot | max_steps=20 release_copies=1 screen_cache=1 | 128 | 45 | 17.0 |
| rec128_shot | 10-30 04:14 | tfork | grpo16.json |  | max_steps=20 release_copies=1 | 128 | 51 | 18.4 |
| rec128e2_shot | 10-30 06:34 | tfork | grpo16.json |  | max_steps=20 release_copies=1 | 128 | 45 | 20.8 |
| rec128e3_shot | 10-30 09:42 | tfork | grpo16.json |  | max_steps=20 release_copies=1 | 128 | 47 | 18.9 |
| rec128e4_shot | 10-30 10:25 | tfork | grpo16.json |  | max_steps=20 release_copies=1 screen_cache=1 | 128 | 49 | 20.3 |
| rec128e5_shot | 10-30 11:01 | tfork | grpo16.json |  | max_steps=20 release_copies=1 screen_cache=1 | 128 | 42 | 19.4 |
| rec128e5b_shot | 10-30 11:29 | tfork | grpo16.json |  | max_steps=20 release_copies=1 screen_cache=1 | 128 | 46 | 27.2 |
| rec30_shot | 10-30 02:45 | tfork | grpo16.json |  | max_steps=30 release_copies=1 | 32 | 14 | 16.7 |
| rec32v2_tfork | 10-26 21:01 | tfork | grpo_batch32v2.json |  | parallel=8 | 256 | 8 | 34.3 |
| rec32x8_h100 | 10-28 02:35 | tfork | grpo_batch32v2.json |  | release_copies=1 | 256 | 13 | 16.6 |
| release_test_aenv | 10-28 00:36 | aenv | grpo_batch32v2.json | rec32v2_tfork | parallel=1 release_copies=1 | 8 | 1 | 4.5 |
| release_test_criu | 10-28 00:45 | criu | grpo_batch32v2.json | rec32v2_tfork | parallel=1 release_copies=1 | 8 | 1 | 5.1 |
| release_test_criu_old10s | 10-28 00:30 | criu | grpo_batch32v2.json | rec32v2_tfork | parallel=1 release_copies=1 | 8 | 1 | 5.5 |
| release_test_tfork | 10-28 00:41 | tfork | grpo_batch32v2.json | rec32v2_tfork | parallel=1 release_copies=1 | 8 | 1 | 4.1 |
| release_test_tfork_old10s | 10-28 00:26 | tfork | grpo_batch32v2.json | rec32v2_tfork | parallel=1 release_copies=1 | 8 | 0 | 4.4 |
| replay31_aenv | 10-26 18:14 | aenv | replay31.json | osw_criu32_capped | parallel=8 | 184 | 3 | 22.2 |
| replay31_aenv_direct | 10-26 20:07 | aenv | replay31.json | osw_criu32_capped | parallel=8 | 184 | 3 | 34.8 |
| replay31_criu | 10-26 17:47 | criu | replay31.json | osw_criu32_capped | parallel=8 | 184 | 3 | 26.9 |
| replay31_tfork | 10-26 17:21 | tfork | replay31.json | osw_criu32_capped | parallel=8 | 184 | 3 | 25.9 |
| replay32_aenv | 10-26 22:51 | aenv | grpo_batch32v2.json | rec32v2_tfork | parallel=8 | 248 | 9 | 47.5 |
| replay32_aenv_rerun1 | 10-26 23:51 | aenv | aenv_rerun1.json | rec32v2_tfork | parallel=8 | 8 | 0 | 5.5 |
| replay32_criu | 10-26 22:14 | criu | grpo_batch32v2.json | rec32v2_tfork | parallel=8 | 256 | 8 | 36.8 |
| replay32_tfork | 10-26 21:40 | tfork | grpo_batch32v2.json | rec32v2_tfork | parallel=8 | 256 | 9 | 33.4 |
| replay32_tfork_overlay | 10-27 13:10 | tfork | grpo_batch32v2.json | rec32v2_tfork | parallel=8 | 256 | 9 | 29.2 |
| replay3_aenv_direct | 10-26 19:58 | aenv | replay3.json | osw_criu32_capped |  | 24 | 0 | 8.0 |
| replay3_tfork | 10-26 16:25 | tfork | replay3.json | osw_criu32_capped |  | 24 | 0 | 9.8 |
| s20b2k_reg | 10-29 22:20 | tfork | grpo_batch32v2.json |  | max_steps=20 release_copies=1 | 39 | 11 | 16.9 |
| shot6_shot | 10-29 23:33 | tfork | shot6.json |  | release_copies=1 | 9 | 6 | 4.8 |
| shot6v2_shot | 10-29 23:41 | tfork | shot6.json |  | release_copies=1 | 18 | 6 | 10.9 |
| shot6v3_shot | 10-30 00:01 | tfork | shot6.json |  | release_copies=1 | 18 | 4 | 11.0 |
| shot6v4_shot | 10-30 00:12 | tfork | shot4_unsolved.json |  | release_copies=1 | 12 | 0 | 10.2 |
| smoke32_tfork | 10-26 14:06 | tfork | grpo_batch32v2.json |  | max_steps=3 parallel=8 | 64 | 0 | 9.9 |
| smoke_PS2 | 10-30 09:27 | tfork | smoke_7a4e.json | rec128e2_shot | max_steps=8 release_copies=1 spec=tage spec_exec=1 spec_max_forks=24 spec_slow=1 spec_prefork=1 screen_cache=1 | 8 | 0 | 11.3 |
| smoke_aenv | 10-26 07:48 | aenv | grpo_batch.json |  | max_steps=3 parallel=1 | 2 | 0 | 1.1 |
| smoke_clean_aenv | 10-27 15:37 | aenv | smoke2.json | rec32v2_tfork | max_steps=3 parallel=2 | 4 | 0 | 1.7 |
| smoke_clean_base_tfork | 10-27 15:39 | tfork | smoke2.json | rec32v2_tfork | max_steps=3 parallel=2 base_fork=1 | 4 | 0 | 2.6 |
| smoke_clean_criu | 10-27 15:35 | criu | smoke2.json | rec32v2_tfork | max_steps=3 parallel=2 | 4 | 0 | 2.3 |
| smoke_clean_tfork | 10-27 15:32 | tfork | smoke2.json | rec32v2_tfork | max_steps=3 parallel=2 | 4 | 0 | 2.2 |
| smoke_cmp_aenv | 10-27 19:24 | aenv | grpo_batch32v2.json | rec32v2_tfork | parallel=1 | 2 | 1 | 3.7 |
| smoke_cmp_tfork | 10-27 19:20 | tfork | grpo_batch32v2.json | rec32v2_tfork | parallel=1 | 2 | 1 | 3.6 |
| smoke_criu | 10-25 17:44 | criu | grpo_batch.json |  | max_steps=3 | 2 | 0 | 1.4 |
| smoke_mem | 10-25 21:33 | criu | tb_tasks.json |  | max_steps=2 | 4 | 0 | 1.6 |
| smoke_min_tfork | 10-27 18:04 | tfork | smoke2.json | rec32v2_tfork | max_steps=2 parallel=1 | 2 | 0 | 1.1 |
| smoke_par | 10-25 21:23 | criu | grpo_batch.json |  | max_steps=3 | 4 | 2 | 2.7 |
| smoke_pass2_aenv | 10-27 18:30 | aenv | grpo_batch32v2.json | rec32v2_tfork | parallel=1 | 2 | 1 | 3.7 |
| smoke_pass2_tfork | 10-27 18:26 | tfork | grpo_batch32v2.json | rec32v2_tfork | parallel=1 | 2 | 1 | 3.6 |
| smoke_pass3_criu | 10-27 18:45 | criu | grpo_batch32v2.json | rec32v2_tfork | parallel=1 | 2 | 1 | 3.8 |
| smoke_pass3_tfork_base | 10-27 18:49 | tfork | grpo_batch32v2.json | rec32v2_tfork | parallel=1 base_fork=1 | 4 | 1 | 7.6 |
| smoke_readme_tfork | 10-27 18:12 | tfork | grpo_batch32v2.json | rec32v2_tfork | parallel=1 | 2 | 1 | 3.6 |
| spec_stress8 | 10-29 16:36 | tfork | spec_tail8.json | grpo_tfork16_e2 | max_steps=6 release_copies=1 replay_latency=4.5 spec_exec=2 | 64 | 0 | 8.1 |
| spec_tail_A | 10-29 14:56 | tfork | spec_tail3.json | grpo_tfork16_e2 | release_copies=1 replay_latency=4.5 | 24 | 0 | 15.1 |
| spec_tail_A8 | 10-29 15:42 | tfork | spec_tail8.json | grpo_tfork16_e2 | release_copies=1 replay_latency=4.5 | 64 | 0 | 16.3 |
| spec_tail_B | 10-29 15:11 | tfork | spec_tail3.json | grpo_tfork16_e2 | release_copies=1 replay_latency=4.5 spec_exec=2 | 2 | 0 | 13.4 |
| spec_tail_B2 | 10-29 15:26 | tfork | spec_tail3.json | grpo_tfork16_e2 | release_copies=1 replay_latency=4.5 spec_exec=2 | 24 | 0 | 12.7 |
| spec_tail_B8 | 10-29 15:59 | tfork | spec_tail8.json | grpo_tfork16_e2 | release_copies=1 replay_latency=4.5 spec_exec=2 | 61 | 0 | 14.5 |
| spec_tail_B8b | 10-29 16:14 | tfork | spec_tail8.json | grpo_tfork16_e2 | release_copies=1 replay_latency=4.5 spec_exec=2 | 34 | 0 | 12.1 |
| spec_tail_B8c | 10-29 16:47 | tfork | spec_tail8.json | grpo_tfork16_e2 | release_copies=1 replay_latency=4.5 spec_exec=2 | 64 | 0 | 25.0 |
| spec_tail_B8d | 10-29 17:24 | tfork | spec_tail8.json | grpo_tfork16_e2 | release_copies=1 replay_latency=4.5 spec_exec=2 spec_max_forks=10 | 64 | 0 | 13.7 |
| spec_tail_B8e | 10-29 17:38 | tfork | spec_tail8.json | grpo_tfork16_e2 | release_copies=1 replay_latency=4.5 spec_exec=2 spec_max_forks=10 | 0 | 0 | 0.8 |
| specab_A | 10-30 02:37 | tfork | grpo16.json | fix16_shot | release_copies=1 | 32 | 7 | 7.6 |
| specab_B | 10-30 02:37 | tfork | grpo16.json | fix16_shot | release_copies=1 spec=tage spec_exec=1 spec_max_forks=64 spec_inplace=1 | 32 | 7 | 7.6 |
| stop15_shot | 10-30 01:35 | tfork | diff15.json |  | release_copies=1 | 15 | 4 | 7.4 |
| stop_test | 10-30 02:12 | tfork | pivot1.json | fix16_shot | release_copies=1 replay_latency=0.0 | 1 | 0 | 2.2 |
| stopped_ckpt_cow_spec_off | 10-25 20:06 | criu | grpo_batch.json |  |  | 40 | 1 | 32.4 |
| stopped_ourcriu_dumprestore_spec_off | 10-25 19:51 | criu | grpo_batch.json |  |  | 0 | 0 | 1.0 |
| stuck_shot | 10-30 02:05 | tfork | stuck.json |  | release_copies=1 | 14 | 1 | 8.6 |
| tfork_failed_rerun | 10-26 13:07 | tfork | tfork_failed.json |  |  | 8 | 0 | 15.0 |
| tfork_failed_rerun2 | 10-26 13:28 | tfork | tfork_failed.json |  |  | 16 | 0 | 13.5 |
| tfork_wave1_repro | 10-26 23:39 | tfork | grpo_batch32v2.json | rec32v2_tfork | parallel=8 | 64 | 9 | 11.7 |
| vlc1_shot | 10-30 00:22 | tfork | vlc1.json |  | release_copies=1 | 3 | 3 | 4.4 |
