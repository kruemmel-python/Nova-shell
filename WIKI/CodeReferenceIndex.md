# Code Reference Index

## Zweck

Diese Seite ist der vollstaendige Symbolindex der aktuellen Nova-shell-Codebasis.
Sie ist nicht als Fliesstext-Architekturseite gedacht, sondern als schnelle Referenz:

- welches Modul existiert
- welche Klassen dort liegen
- welche Methoden eine Klasse hat
- welche Hilfsfunktionen auf Modulebene existieren

Die erklaerenden Seiten bleiben:

- [ClassReference](./ClassReference.md)
- [ParserAndASTReference](./ParserAndASTReference.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [ShellCommandReference](./ShellCommandReference.md)

Diese Seite beantwortet dagegen:

> Wo liegt ein Symbol genau und welche Methoden gehoeren dazu?

## Wie dieser Index benutzt werden sollte

Diese Seite ist am staerksten, wenn du bereits einen Symbolnamen, ein Modul oder eine Klasse suchst.
Sie ist nicht der beste erste Einstieg fuer neue Nutzer, sondern die Referenz nach Architektur- oder Nutzungsseiten.

Empfohlene Reihenfolge:

1. erst Fachseite lesen, zum Beispiel [NovaRuntime](./NovaRuntime.md) oder [NovaAgents](./NovaAgents.md)
2. dann in diesem Index das konkrete Symbol suchen
3. danach in den Quelltext oder in die passende Methodenreferenz gehen

## Typische Lookup-Fragen

### Ich kenne ein Modul, aber nicht die Klasse

Suche nach dem Modulabschnitt, zum Beispiel `nova.runtime.runtime` oder `nova.mesh.registry`.

### Ich kenne die Klasse, aber nicht ihre Methoden

Gehe zum passenden Abschnitt und nutze die aufgelisteten Methoden als Startpunkt fuer Quelltext oder Tests.

### Ich kenne nur das Kommando

Dann beginne nicht hier, sondern in [ShellCommandReference](./ShellCommandReference.md), und springe von dort zu Symbolen weiter.

## Testbare Symbolsuche im Repository

Wenn du die Wiki mit dem echten Quellbaum abgleichen willst:

```powershell
rg "class NovaRuntime|def run\\(" nova
rg "_run_ai|_ns_run|route\\(" nova_shell.py
```

Das ersetzt die Wiki nicht, ist aber die schnellste Querverifikation.

## Parser und Graph

### `nova.parser.ast`

Klassen:

- `SourceSpan`
- `ImportDeclaration`
- `AgentDeclaration`
- `DatasetDeclaration`
- `ToolDeclaration`
- `ServiceDeclaration`
- `PackageDeclaration`
- `StateDeclaration`
- `SystemDeclaration`
- `EventDeclaration`
- `FlowStep`
- `FlowDeclaration`
- `NovaAST`

`NovaAST`-Methoden:

- `by_type`
- `by_name`
- `flows`
- `imports`
- `agents`
- `datasets`
- `tools`
- `services`
- `packages`
- `events`
- `states`
- `systems`

### `nova.parser.errors`

Klassen:

- `NovaSyntaxError`

### `nova.parser.parser`

Klassen:

- `NovaParser`

`NovaParser`-Methoden:

- `register_extension`
- `parse_file`
- `parse`
- `_parse_import`
- `_collect_block`
- `_parse_block`
- `_parse_properties`
- `_parse_flow_body`
- `_parse_flow_step`
- `_split_alias`
- `_parse_value`
- `_split_comma`
- `_strip_inline_comment`

### `nova.graph.compiler`

Klassen:

- `GraphCompileError`
- `GraphCycleError`
- `_DefinitionIndex`
- `NovaGraphCompiler`

`NovaGraphCompiler`-Methoden:

- `compile`
- `_compile_flow`
- `_compile_flow_step`
- `_agent_action_and_inputs`
- `_resolve_system`
- `_resolve_property`
- `_normalize_list_property`
- `_normalize_dict_property`
- `_infer_backend`
- `_infer_capability`
- `_compile_event_edges`
- `_event_flows`

### `nova.graph.model`

Klassen:

- `DatasetNode`
- `ToolNode`
- `AgentNode`
- `ServiceNode`
- `PackageNode`
- `FlowNode`
- `EventNode`
- `ExecutionEdge`
- `ExecutionGraph`

`ExecutionGraph`-Methoden:

- `add_node`
- `add_edge`
- `successors`
- `flow_root`
- `closure_for_flow`
- `topological_order`
- `to_dict`
- `_serialize_node`

## Agents und AI

### `nova.agents.evals`

Funktionen:

- `_truncate_text`
- `_sanitize_metadata`

Klassen:

- `AgentEvalStore`

`AgentEvalStore`-Methoden:

- `_init_schema`
- `close`
- `record`
- `list_recent`
- `snapshot`
- `_score`

### `nova.agents.memory`

Funktionen:

- `_truncate_text`
- `_sanitize_metadata`

Klassen:

- `DistributedMemoryStore`

`DistributedMemoryStore`-Methoden:

- `_init_schema`
- `close`
- `append`
- `search`
- `snapshot`

### `nova.runtime.blob_seed`

Konstanten:

- `INLINE_BLOB_PREFIX`

Klassen:

- `NovaBlobSeed`
- `NovaBlobGenerator`

`NovaBlobGenerator`-Methoden:

- `detect_kind`
- `create_from_bytes`
- `create_from_text`
- `create_from_file`
- `inline_seed`
- `write_blob`
- `default_path`
- `load_blob`
- `verify`
- `unpack_bytes`
- `unpack_text`

### `nova.agents.prompts`

Klassen:

- `PromptRegistry`

`PromptRegistry`-Methoden:

- `_init_schema`
- `close`
- `register_agent`
- `resolve`
- `active_version`
- `list_versions`
- `snapshot`

### `nova.agents.providers`

Klassen:

- `ProviderAdapter`
- `LocalProviderAdapter`
- `ShellProviderAdapter`
- `AtheriaProviderAdapter`
- `ProviderRegistry`

Methoden:

- `ProviderAdapter.invoke`
- `LocalProviderAdapter.invoke`
- `ShellProviderAdapter.invoke`
- `AtheriaProviderAdapter.invoke`
- `ProviderRegistry.resolve`
- `ProviderRegistry.execute`

### `nova.agents.runtime`

Klassen:

- `AgentSpecification`
- `AgentTask`
- `AgentExecutionResult`
- `AgentRuntime`

Methoden:

- `AgentExecutionResult.to_dict`
- `AgentRuntime.register`
- `AgentRuntime.specification`
- `AgentRuntime.execute`
- `AgentRuntime._render_output`
- `AgentRuntime._provider_output`
- `AgentRuntime._enforce_governance`
- `AgentRuntime._memory_scope`
- `AgentRuntime._summarize_input`
- `AgentRuntime._bounded_text`
- `AgentRuntime._compact_memory_context`

### `nova.agents.sandbox`

Klassen:

- `ToolSandbox`

Methoden:

- `authorize`
- `snapshot`

## Events, Mesh und Protokolle

### `nova.events.bus`

Klassen:

- `Event`
- `EventSubscription`
- `EventBus`

Methoden:

- `Event.to_dict`
- `EventBus.subscribe`
- `EventBus.publish`

### `nova.mesh.control_plane`

Klassen:

- `MeshTaskRecord`
- `PersistentMeshControlPlane`

Methoden:

- `MeshTaskRecord.to_dict`
- `PersistentMeshControlPlane._init_schema`
- `PersistentMeshControlPlane.close`
- `PersistentMeshControlPlane.register_worker`
- `PersistentMeshControlPlane.heartbeat`
- `PersistentMeshControlPlane.start_task`
- `PersistentMeshControlPlane.finish_task`
- `PersistentMeshControlPlane.list_workers`
- `PersistentMeshControlPlane.list_tasks`
- `PersistentMeshControlPlane.snapshot`

### `nova.mesh.protocol`

Klassen:

- `ExecutorTask`
- `ExecutorResult`

Methoden:

- `ExecutorTask.to_dict`
- `ExecutorTask.from_dispatch_task`
- `ExecutorTask.from_dict`
- `ExecutorResult.to_dict`

### `nova.mesh.registry`

Klassen:

- `WorkerNode`
- `MeshRegistry`

Methoden:

- `WorkerNode.heartbeat`
- `WorkerNode.to_dict`
- `MeshRegistry.register`
- `MeshRegistry.heartbeat`
- `MeshRegistry.list_workers`
- `MeshRegistry.candidates`
- `MeshRegistry.select`
- `MeshRegistry.dispatch`
- `MeshRegistry._dispatch_protocol`
- `MeshRegistry._matches_selector`
- `MeshRegistry._matches_tenant`
- `MeshRegistry._matches_transport`
- `MeshRegistry._ssl_context_for_worker`
- `MeshRegistry.health_report`
- `MeshRegistry.snapshot`

## Runtime

### `nova.runtime.api`

Klassen:

- `NovaControlPlaneAPIServer`

Methoden:

- `start`
- `stop`
- `status`

### `nova.runtime.backends`

Klassen:

- `BackendExecutionRequest`
- `LocalPythonBackend`
- `LocalSystemBackend`
- `ShellCommandBackend`
- `BackendRouter`

Methoden:

- `LocalPythonBackend.execute`
- `LocalSystemBackend.execute`
- `ShellCommandBackend.execute`
- `BackendRouter.execute`
- `BackendRouter._native_backend_for_operation`
- `BackendRouter._build_shell_command`
- `BackendRouter._load_data`

### `nova.runtime.cluster`

Klassen:

- `LeaderLease`
- `DeploymentRevision`
- `ClusterPlane`

Methoden:

- `LeaderLease.to_dict`
- `DeploymentRevision.to_dict`
- `ClusterPlane._open_connection`
- `ClusterPlane._ensure_connection`
- `ClusterPlane._init_schema`
- `ClusterPlane.close`
- `ClusterPlane.acquire_leadership`
- `ClusterPlane.renew_leadership`
- `ClusterPlane.release_leadership`
- `ClusterPlane.leader_status`
- `ClusterPlane.create_rollout`
- `ClusterPlane.get_revision`
- `ClusterPlane.promote_revision`
- `ClusterPlane.rollback`
- `ClusterPlane.deployment_status`
- `ClusterPlane.record_health`
- `ClusterPlane.list_health`
- `ClusterPlane.health_summary`
- `ClusterPlane.evaluate_rollout`
- `ClusterPlane.register_playbook`
- `ClusterPlane.get_playbook`
- `ClusterPlane.list_playbooks`
- `ClusterPlane.run_playbook`
- `ClusterPlane.list_recovery_runs`
- `ClusterPlane.snapshot`

### `nova.runtime.consensus`

Klassen:

- `ConsensusPeer`
- `ConsensusLogEntry`
- `ControlPlaneConsensus`

Methoden:

- `ConsensusPeer.to_dict`
- `ConsensusLogEntry.to_dict`
- `ControlPlaneConsensus._open_connection`
- `ControlPlaneConsensus._ensure_connection`
- `ControlPlaneConsensus._init_schema`
- `ControlPlaneConsensus.close`
- `ControlPlaneConsensus._set_meta`
- `ControlPlaneConsensus._get_meta`
- `ControlPlaneConsensus.touch_leader_contact`
- `ControlPlaneConsensus.leader_contact_at`
- `ControlPlaneConsensus.configure`
- `ControlPlaneConsensus.status`
- `ControlPlaneConsensus.is_enabled`
- `ControlPlaneConsensus.set_enabled`
- `ControlPlaneConsensus._update_state`
- `ControlPlaneConsensus.register_peer`
- `ControlPlaneConsensus.update_peer`
- `ControlPlaneConsensus.remove_peer`
- `ControlPlaneConsensus.list_peers`
- `ControlPlaneConsensus.latest_snapshot`
- `ControlPlaneConsensus.needs_election`
- `ControlPlaneConsensus.quorum_size`
- `ControlPlaneConsensus.last_log_index`
- `ControlPlaneConsensus.last_log_term`
- `ControlPlaneConsensus.get_entry`
- `ControlPlaneConsensus.list_log`
- `ControlPlaneConsensus.request_vote`
- `ControlPlaneConsensus.start_election`
- `ControlPlaneConsensus.append_entries`
- `ControlPlaneConsensus.append_local`
- `ControlPlaneConsensus.mark_committed`
- `ControlPlaneConsensus.mark_applied`

### `nova.runtime.context`

Funktionen:

- `to_jsonable`

Klassen:

- `CommandExecutor`
- `CommandExecution`
- `DatasetSnapshot`
- `NodeExecutionRecord`
- `FlowExecutionRecord`
- `CompiledNovaProgram`
- `RuntimeContext`
- `NovaRuntimeResult`

Methoden:

- `CommandExecutor.execute`
- `CommandExecution.to_dict`
- `DatasetSnapshot.update`
- `DatasetSnapshot.to_dict`
- `NodeExecutionRecord.to_dict`
- `FlowExecutionRecord.to_dict`
- `CompiledNovaProgram.to_dict`
- `RuntimeContext.close`
- `RuntimeContext.resolve_reference`
- `RuntimeContext.snapshot`
- `NovaRuntimeResult.to_dict`
- `NovaRuntimeResult.to_json`

### `nova.runtime.control_plane`

Klassen:

- `QueuedTask`
- `ScheduledJob`
- `DurableEventRecord`
- `DurableControlPlane`

Methoden:

- `QueuedTask.to_dict`
- `ScheduledJob.to_dict`
- `DurableEventRecord.to_dict`
- `DurableControlPlane._open_connection`
- `DurableControlPlane._ensure_connection`
- `DurableControlPlane._init_schema`
- `DurableControlPlane.close`
- `DurableControlPlane.enqueue_task`
- `DurableControlPlane.find_task_by_idempotency`
- `DurableControlPlane.acquire_scheduler_lease`
- `DurableControlPlane.scheduler_owner`
- `DurableControlPlane.recover_stale_tasks`
- `DurableControlPlane.record_task_effect`
- `DurableControlPlane.get_task_effect`
- `DurableControlPlane.get_task_effect_by_idempotency`
- `DurableControlPlane.claim_tasks`
- `DurableControlPlane.complete_task`
- `DurableControlPlane.fail_task`
- `DurableControlPlane.list_tasks`
- `DurableControlPlane.schedule_job`
- `DurableControlPlane.list_schedules`
- `DurableControlPlane.scheduler_tick`
- `DurableControlPlane.publish_event`
- `DurableControlPlane.replay_events`
- `DurableControlPlane.record_daemon_state`
- `DurableControlPlane.daemon_status`
- `DurableControlPlane.snapshot`

### `nova.runtime.executor_daemon`

Funktionen:

- `main`

Klassen:

- `ActiveJob`
- `ExecutorDaemon`

Methoden:

- `ActiveJob.snapshot`
- `ExecutorDaemon._authorized`
- `ExecutorDaemon.start`
- `ExecutorDaemon.stop`
- `ExecutorDaemon.execute`
- `ExecutorDaemon.execute_async`
- `ExecutorDaemon.stream`
- `ExecutorDaemon.cancel`
- `ExecutorDaemon.job_status`
- `ExecutorDaemon._spawn_job`
- `ExecutorDaemon._start_process`
- `ExecutorDaemon._job_env`
- `ExecutorDaemon._drain_stream`
- `ExecutorDaemon._terminate_process`

### `nova.runtime.executors`

Funktionen:

- `execute_backend_task`

Klassen:

- `ExecutorRecord`
- `_StreamTee`
- `_PythonAdapter`
- `_CppAdapter`
- `_GpuAdapter`
- `_WasmAdapter`
- `_AiAdapter`
- `NativeExecutorServer`
- `NativeExecutorManager`

Methoden:

- `ExecutorRecord.to_dict`
- `_StreamTee.write`
- `_StreamTee.flush`
- `_StreamTee.rendered`
- `_PythonAdapter.execute`
- `_CppAdapter.execute`
- `_GpuAdapter.execute`
- `_WasmAdapter.execute`
- `_AiAdapter.execute`
- `NativeExecutorServer.start`
- `NativeExecutorServer.stop`
- `NativeExecutorManager._init_schema`
- `NativeExecutorManager.close`
- `NativeExecutorManager.ensure_backend`
- `NativeExecutorManager.get_backend`
- `NativeExecutorManager.list_backends`
- `NativeExecutorManager.execute`
- `NativeExecutorManager.execute_async`
- `NativeExecutorManager.cancel`
- `NativeExecutorManager.stream`
- `NativeExecutorManager.stop_backend`
- `NativeExecutorManager.restart_backend`
- `NativeExecutorManager.recover`
- `NativeExecutorManager.snapshot`
- `NativeExecutorManager._endpoint_file`
- `NativeExecutorManager._log_file`
- `NativeExecutorManager._start_backend`
- `NativeExecutorManager._healthy`
- `NativeExecutorManager._request`
- `NativeExecutorManager._mark_request`
- `NativeExecutorManager._update_record_status`
- `NativeExecutorManager._daemon_env`

### `nova.runtime.observability`

Klassen:

- `RuntimeTraceRecord`
- `RuntimeObservability`

Methoden:

- `RuntimeTraceRecord.to_dict`
- `RuntimeObservability.record`
- `RuntimeObservability.add_alert_rule`
- `RuntimeObservability.traces`
- `RuntimeObservability.histogram`
- `RuntimeObservability.alerts`
- `RuntimeObservability.validate_trace_store`
- `RuntimeObservability.snapshot`

### `nova.runtime.operations`

Klassen:

- `RuntimeOperations`

Methoden:

- `_init_schema`
- `close`
- `register_component`
- `validate_migrations`
- `set_failpoint`
- `clear_failpoint`
- `list_failpoints`
- `check_failpoint`
- `create_backup`
- `list_backups`
- `restore_backup`
- `run_load`
- `list_load_runs`
- `snapshot`

### `nova.runtime.policy`

Klassen:

- `AuditRecord`
- `RuntimeAuditLog`
- `RuntimePolicy`

Methoden:

- `AuditRecord.to_dict`
- `RuntimeAuditLog.record`
- `RuntimeAuditLog.snapshot`
- `RuntimePolicy.configure`
- `RuntimePolicy.can_admin`
- `RuntimePolicy.can_operate`
- `RuntimePolicy.authorize_roles`
- `RuntimePolicy.authorize_tenant`
- `RuntimePolicy.permits_tenant`
- `RuntimePolicy.authorize_namespace`
- `RuntimePolicy.permits_namespace`
- `RuntimePolicy.resolve_quotas`
- `RuntimePolicy.snapshot`
- `RuntimePolicy._normalize_roles`

### `nova.runtime.replication`

Klassen:

- `ReplicatedLogStore`

Methoden:

- `_open_connection`
- `_ensure_connection`
- `_init_schema`
- `close`
- `register_peer`
- `list_peers`
- `append_record`
- `list_records`
- `update_peer_status`
- `sync`
- `snapshot`

### `nova.runtime.runtime`

Klassen:

- `NovaRuntime`

`NovaRuntime`-Methoden:

- `close`
- `compile`
- `load`
- `run`
- `execute_flow`
- `emit`
- `snapshot`
- `resume`
- `register_tenant`
- `select_tenant`
- `select_namespace`
- `issue_token`
- `verify_token`
- `login`
- `logout`
- `whoami`
- `revoke_token`
- `store_secret`
- `resolve_secret`
- `set_tls_profile`
- `set_trust_policy`
- `onboard_worker`
- `rotate_worker_certificate`
- `create_certificate_authority`
- `issue_certificate`
- `revoke_certificate`
- `acquire_leadership`
- `renew_leadership`
- `release_leadership`
- `leader_status`
- `create_rollout`
- `promote_revision`
- `rollback_deployment`
- `deployment_status`
- `list_services`
- `list_packages`
- `discover_service`
- `evaluate_service_autoscaling`
- `list_service_configs`
- `list_service_volumes`
- `list_service_ingress`
- `list_traffic_routes`
- `list_traffic_probes`
- `list_secret_mounts`
- `probe_service_traffic`
- `shift_service_traffic`
- `route_service_request`
- `start_traffic_proxy`
- `stop_traffic_proxy`
- `traffic_proxy_status`
- `scale_service`
- `executor_status`
- `restart_executor_backend`
- `stop_executor_backend`
- `cancel_executor_request`
- `stream_executor_request`
- `list_traces`
- `list_alerts`
- `validate_snapshot_file`
- `install_package`
- `deploy_service`
- `register_recovery_playbook`
- `list_recovery_playbooks`
- `run_recovery_playbook`
- `enqueue_flow`
- `schedule_flow`
- `schedule_event`
- `scheduler_tick`
- `run_pending_tasks`
- `list_queue_tasks`
- `list_schedules`
- `replay_event_log`
- `record_deployment_health`
- `evaluate_rollout`
- `control_status`
- `create_backup`
- `list_backups`
- `restore_backup`
- `validate_migrations`
- `set_failpoint`
- `clear_failpoint`
- `list_failpoints`
- `run_load_test`
- `write_lockfile`
- `publish_toolchain_package`
- `list_toolchain_packages`
- `format_source`
- `lint_source`
- `toolchain_symbols`
- `toolchain_hover`
- `run_program_tests`
- `register_prompt_version`
- `list_prompt_versions`
- `search_agent_memory`
- `list_agent_evals`
- `start_control_daemon`
- `stop_control_daemon`
- `control_tick`
- `register_replica_peer`
- `list_replica_peers`
- `list_replicated_records`
- `replay_state_log`
- `list_state`
- `list_workflow_runs`
- `replay_workflow_run`
- `export_metrics`
- `consensus_status`
- `remove_consensus_peer`
- `register_consensus_peer`
- `list_consensus_peers`
- `consensus_log`
- `consensus_snapshot`
- `start_consensus_election`
- `send_consensus_heartbeats`
- `compact_consensus_log`
- `install_consensus_snapshot`
- `sync_consensus`
- `consensus_request_vote`
- `consensus_append_entries`
- `sync_replication`
- `apply_replica_record`
- `_commit_consensus_mutation`
- `_read_consensus_result`
- `_apply_consensus_entry`
- `_send_consensus_vote`
- `_send_consensus_append`
- `_post_control_plane`
- `_maybe_failpoint`
- `_register_program_resources`
- `_configure_platform`
- `_register_event_bindings`
- `_restore_context_payload`
- `_require_context`
- `_refresh_state_cache`
- `_current_quotas`
- `_enforce_quota`
- `_tenant_queue_depth`
- `_tenant_schedule_count`
- `_tenant_state_count`
- `_tenant_worker_count`
- `_send_replica_record`
- `start_control_api`
- `stop_control_api`
- `control_api_status`
- `_resolve_path`
- `_install_package_local`
- `_deploy_service_local`
- `_execute_recovery_step`
- `_run_control_task`
- `_handle_bound_event`
- `_entry_flows`
- `_event_flows`
- `_execute_node`
- `_execute_tool`
- `_build_remote_command`
- `_execute_tool_local`
- `_tool_rss_fetch`
- `_tool_atheria_embed`
- `_tool_system_log`
- `_tool_event_emit`
- `_tool_flow_run`
- `_tool_state_set`
- `_tool_state_get`
- `_tool_service_deploy`
- `_tool_service_status`
- `_tool_package_install`
- `_tool_package_status`
- `_run_declared_command`
- `_bootstrap_dataset_records`
- `_normalize_record`
- `_publish_event`
- `assert_admin_access`
- `assert_operator_access`
- `_authorize_flow`
- `_authorize_node`
- `_audit`
- `_begin_trace`
- `_child_trace`
- `_current_trace`
- `_end_trace`

## Toolchain und Wiki

### `nova.toolchain.formatter`

Klassen:

- `NovaFormatter`

Methoden:

- `format_ast`
- `format_source`
- `_render_step`
- `_render_value`

### `nova.toolchain.linter`

Klassen:

- `NovaLintDiagnostic`
- `NovaLinter`

Methoden:

- `NovaLintDiagnostic.to_dict`
- `NovaLinter.lint`
- `NovaLinter._lint_flow`

### `nova.toolchain.loader`

Klassen:

- `ResolvedNovaModule`
- `LoadedNovaProgram`
- `NovaModuleLoader`

Methoden:

- `NovaModuleLoader.load`
- `NovaModuleLoader.write_lockfile`
- `NovaModuleLoader._load_module`
- `NovaModuleLoader._resolve_import`
- `NovaModuleLoader._checksum_path`
- `NovaModuleLoader._checksum_bytes`

### `nova.toolchain.lsp`

Klassen:

- `NovaLanguageServerFacade`

Methoden:

- `symbols`
- `hover`
- `diagnostics`
- `completions`

### `nova.toolchain.registry`

Klassen:

- `NovaPackageRegistry`

Methoden:

- `publish`
- `resolve`
- `list_packages`
- `snapshot`
- `_split_target`
- `_checksum`
- `_load`
- `_store`

### `nova.toolchain.testing`

Klassen:

- `NovaTestCaseResult`
- `NovaTestSuiteResult`
- `NovaTestRunner`

Methoden:

- `NovaTestCaseResult.to_dict`
- `NovaTestSuiteResult.to_dict`
- `NovaTestRunner.run`
- `NovaTestRunner._assert_flow_expectations`

### `nova.wiki.site`

Funktionen:

- `_slugify`
- `_convert_href`
- `_render_plain_fragment`
- `_render_inline`
- `_split_table_row`
- `_is_table_separator`
- `_strip_markdown`
- `_extract_title`
- `_extract_excerpt`
- `render_markdown`
- `_wiki_css`
- `_wiki_js`

Klassen:

- `WikiHeading`
- `WikiPage`
- `WikiBuildResult`
- `NovaWikiSiteBuilder`
- `NovaWikiSiteServer`

Methoden:

- `WikiBuildResult.to_dict`
- `NovaWikiSiteBuilder.build`
- `NovaWikiSiteBuilder._load_pages`
- `NovaWikiSiteBuilder._parse_sidebar`
- `NovaWikiSiteBuilder._load_footer_html`
- `NovaWikiSiteBuilder._render_page`
- `NovaWikiSiteBuilder._render_nav`
- `NovaWikiSiteBuilder._render_toc`
- `NovaWikiSiteServer.start`
- `NovaWikiSiteServer.stop`
- `NovaWikiSiteServer.status`
- `NovaWikiSiteServer.url`

## Shell-Runtime und Legacy-Pfad

### `nova_shell.py` Modul-Funktionen

- `_is_windows_runtime`
- `safe_system_name`
- `cleanup_temp_tree`
- `safe_machine_name`
- `safe_platform_string`
- `_trend_focus_labels`
- `_trend_driver_text`
- `render_trend_explanation`
- `render_morning_briefing_summary`
- `configure_sideload_paths`
- `module_available`
- `load_runtime_config`
- `parse_dotenv_text`
- `load_dotenv_files`
- `_resolve_vswhere_path`
- `_run_vswhere`
- `resolve_gxx_command`
- `resolve_cl_command`
- `_resolve_runtime_asset_path`
- `_resolve_bundled_emcc_wrapper`
- `resolve_emcc_command`
- `build_tool_subprocess_env`
- `split_command`
- `command_name`
- `main`

### `nova_shell.py` Datentypen und Engines

Klassen:

- `PipelineType`
- `CommandResult`
- `NovaShellCommandExecutor`
- `PipelineNode`
- `PipelineGraph`
- `AIProviderSpec`
- `AIAgentDefinition`
- `VectorMemoryEntry`
- `ToolSchemaDefinition`
- `AgentRuntimeInstance`
- `AgentGraphDefinition`
- `AtheriaSensorPluginSpec`
- `LensForkArtifact`
- `AutoRAGWatcherSpec`
- `LocalManagedWorker`
- `GPUTaskGraphArtifact`
- `PythonEngine`
- `CppEngine`
- `GPUEngine`
- `DataEngine`
- `SystemEngine`
- `EventBus`
- `NovaFabric`
- `PolicyEngine`
- `MeshScheduler`
- `NovaZeroPool`
- `FlowStateStore`
- `GCounterCRDT`
- `LWWMapCRDT`
- `NovaLensStore`
- [NovaLens](./NovaLens.md): Entwicklererklaerung fuer `lineage.db`, `cas/` und effiziente Snapshot-Speicherung
- `BaseAtheriaSensorPlugin`
- `AtheriaSensorRegistry`
- `NovaComputeJIT`
- `RemoteEngine`
- `PythonFlowStateProxy`
- `PythonFlowProxy`
- `WasmEngine`
- `NovaOptimizer`
- `ReactiveTrigger`
- `ReactiveFlowEngine`
- `GuardPolicyStore`
- `FabricRemoteBridge`
- `GraphArtifact`
- `NovaGraphCompiler`
- `NovaSynth`
- `NovaVectorMemory`
- `NovaAtheriaRuntime`
- `NovaAIProviderRuntime`
- `VisionServer`
- `MeshWorkerServer`
- `NovaShell`

Wichtige Methoden:

- `NovaShellCommandExecutor.execute`
- `PipelineGraph.add`
- `PythonEngine.execute`
- `CppEngine.compile_and_run`
- `CppEngine.compile_to_wasm_and_run`
- `GPUEngine.run_kernel`
- `DataEngine.load_csv`
- `DataEngine.load_csv_arrow`
- `SystemEngine.execute`
- `EventBus.subscribe`
- `EventBus.emit`
- `EventBus.last`
- `MeshScheduler.add_worker`
- `MeshScheduler.list_workers`
- `MeshScheduler.select_worker`
- `RemoteEngine.execute`
- `WasmEngine.execute`
- `VisionServer.start`
- `VisionServer.stop`
- `MeshWorkerServer.serve`

### `NovaShell`

`NovaShell` ist die groesste Klasse des Projekts.
Sie enthaelt Routing, Shell-Kommandos, Bruecken in die deklarative Runtime, Worker-Steuerung, AI-, Tool- und Plattformlogik.

Methodengruppen:

- Shell-Grundfunktionen wie `_doctor`, `_help`, `_pwd`, `_cd`
- Wiki-Funktionen wie `_run_wiki`, `_build_wiki_payload`, `_ensure_wiki_server`
- deklarative Runtime-Funktionen wie `_ns_run`, `_ns_graph`, `_ns_control`, `_ns_snapshot`, `_ns_resume`
- Compute-Funktionen wie `_run_python`, `_run_cpp`, `_run_cpp_sandbox`, `_run_gpu`, `_run_wasm`
- AI- und Agentenfunktionen wie `_run_ai`, `_run_atheria`, `_run_agent`, `_run_agent_once`, `_run_agent_instance_message`
- Tool- und Memory-Funktionen wie `_run_tool`, `_run_memory`
- Mesh- und Remote-Funktionen wie `_run_mesh`, `_run_remote`, `_assign_swarm_worker`
- Sicherheitsfunktionen wie `_run_guard`, `_resolve_guard_policy_reference`
- Pipeline- und Routingfunktionen wie `_split_pipeline`, `_execute_stage`, `_route_internal`, `route`

Die vollstaendige Methodenliste von `NovaShell` steht in [ShellCommandReference](./ShellCommandReference.md) nach Kommandofamilien gegliedert und in [ClassReference](./ClassReference.md) in konzeptioneller Form.

## Wie man diesen Index mit anderen Seiten kombiniert

Nutze:

- [ClassReference](./ClassReference.md) fuer konzeptionelle Einordnung von Klassen
- [RuntimeMethodReference](./RuntimeMethodReference.md) fuer die wichtigsten Laufzeitmethoden mit Bedeutung
- [ShellCommandReference](./ShellCommandReference.md) fuer den Weg von CLI-Kommando zu Handler
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md) fuer die eigentlichen Arbeits- und Programmiermuster

## Typische Einstiege nach Aufgabe

### Ich will einen CLI-Handler finden

1. [ShellCommandReference](./ShellCommandReference.md)
2. danach in diesem Index zu `nova_shell.py`

### Ich will wissen, wo ein Runtime-Verhalten sitzt

1. [NovaRuntime](./NovaRuntime.md)
2. [RuntimeMethodReference](./RuntimeMethodReference.md)
3. danach in diesem Index zu `nova.runtime.*`

### Ich will Parser, AST oder Graph verstehen

1. [NovaLanguage](./NovaLanguage.md)
2. [ParserAndASTReference](./ParserAndASTReference.md)
3. danach in diesem Index zu `nova.parser.*` und `nova.graph.*`

## Verwandte Seiten

- [ClassReference](./ClassReference.md)
- [RuntimeMethodReference](./RuntimeMethodReference.md)
- [ShellCommandReference](./ShellCommandReference.md)
- [ProgrammingWithNovaShell](./ProgrammingWithNovaShell.md)
- [PageTemplate](./PageTemplate.md)
