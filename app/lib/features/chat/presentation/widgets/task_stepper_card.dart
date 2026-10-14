import 'dart:async';
import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../../../../core/theme/tokens.dart';
import '../../../../core/widgets/glass_surface.dart';
import 'secure_input_sheet.dart';

class TaskStepItem {
  final String title;
  final String status; // 'completed', 'running', 'pending', 'failed'
  final String? detail;

  const TaskStepItem({
    required this.title,
    required this.status,
    this.detail,
  });
}

class TaskStepperCard extends StatefulWidget {
  final String taskId;
  final String workflow;
  final String initialStatus;
  final int initialProgress;
  final VoidCallback? onCompleted;
  final VoidCallback? onNavigateToVault;
  final Function(String inputType, String prompt)? onRequestInput;

  const TaskStepperCard({
    super.key,
    required this.taskId,
    this.workflow = 'download_eaadhaar',
    this.initialStatus = 'RUNNING',
    this.initialProgress = 15,
    this.onCompleted,
    this.onNavigateToVault,
    this.onRequestInput,
  });

  @override
  State<TaskStepperCard> createState() => _TaskStepperCardState();
}

class _TaskStepperCardState extends State<TaskStepperCard> {
  late String _currentStatus;
  late int _progress;
  RealtimeChannel? _realtimeChannel;
  final List<TaskStepItem> _steps = [];
  String? _statusMessage;

  @override
  void initState() {
    super.initState();
    _currentStatus = widget.initialStatus;
    _progress = widget.initialProgress;
    _initDefaultSteps();
    _subscribeToTaskEvents();
  }

  void _initDefaultSteps() {
    _steps.clear();
    _steps.addAll([
      TaskStepItem(
        title: 'Validate request & security policy',
        status: _progress > 20 ? 'completed' : (_progress > 0 ? 'running' : 'pending'),
      ),
      TaskStepItem(
        title: 'Connect to UIDAI portal',
        status: _progress > 40 ? 'completed' : (_progress > 20 ? 'running' : 'pending'),
      ),
      TaskStepItem(
        title: 'Verify Aadhaar & OTP challenge',
        status: _progress > 70 ? 'completed' : (_progress > 40 ? 'running' : 'pending'),
      ),
      TaskStepItem(
        title: 'Download & deposit encrypted e-Aadhaar in Vault',
        status: _progress >= 100 ? 'completed' : (_progress > 70 ? 'running' : 'pending'),
      ),
    ]);
  }

  void _subscribeToTaskEvents() {
    try {
      final client = Supabase.instance.client;
      _realtimeChannel = client
          .channel('task_events:${widget.taskId}')
          .onPostgresChanges(
            event: PostgresChangeEvent.insert,
            schema: 'public',
            table: 'task_events',
            filter: PostgresChangeFilter(
              type: PostgresChangeFilterType.eq,
              column: 'task_id',
              value: widget.taskId,
            ),
            callback: (payload) {
              final newRecord = payload.newRecord;
              if (newRecord.isNotEmpty && mounted) {
                final status = newRecord['status']?.toString() ?? _currentStatus;
                final progress = (newRecord['progress'] as num?)?.toInt() ?? _progress;
                final message = newRecord['message']?.toString();
                setState(() {
                  _currentStatus = status;
                  _progress = progress;
                  _statusMessage = message;
                  _updateStepsFromStatus(status, progress);
                });

                if (status == 'COMPLETED') {
                  widget.onCompleted?.call();
                }
              }
            },
          )
          .subscribe();
    } catch (_) {
      // In tests or offline mode, channel subscription is gracefully skipped
    }
  }

  void _updateStepsFromStatus(String status, int progress) {
    _initDefaultSteps();
  }

  @override
  void dispose() {
    try {
      if (_realtimeChannel != null) {
        Supabase.instance.client.removeChannel(_realtimeChannel!);
      }
    } catch (_) {}
    super.dispose();
  }

  Future<void> _handleProvideInput() async {
    final isCaptcha = _statusMessage?.toLowerCase().contains('captcha') ?? false;
    final inputType = isCaptcha ? SecureInputType.captcha : SecureInputType.otp;
    final title = isCaptcha ? 'Enter Security CAPTCHA' : 'Enter Verification OTP';
    final subtitle = isCaptcha ? 'Enter characters shown in challenge' : '6-digit OTP sent to registered mobile';

    final result = await SecureInputSheet.show(
      context: context,
      inputType: inputType,
      title: title,
      subtitle: subtitle,
    );

    if (result != null && mounted) {
      setState(() {
        _currentStatus = isCaptcha ? 'RUNNING' : 'AUTHENTICATING';
        _progress = isCaptcha ? 45 : 75;
        _initDefaultSteps();
      });
      // In production: send input via POST /api/v1/tasks/{id}/input
    }
  }

  @override
  Widget build(BuildContext context) {
    final isCompleted = _currentStatus == 'COMPLETED' || _progress >= 100;
    final isWaitingForUser = _currentStatus == 'WAITING_FOR_USER';
    final isFailed = _currentStatus == 'FAILED';

    return GlassSurface(
      margin: const EdgeInsets.symmetric(vertical: AppSpacing.space12),
      padding: const EdgeInsets.all(AppSpacing.space16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Header: Workflow title & status pill
          Row(
            children: [
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: AppColors.pitchBlack,
                  shape: BoxShape.circle,
                  border: Border.all(color: AppColors.borderWhite, width: 1.0),
                ),
                child: const Icon(Icons.bolt, size: 18, color: AppColors.pureWhite),
              ),
              const SizedBox(width: AppSpacing.space12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _getWorkflowTitle(widget.workflow),
                      style: AppTypography.labelLarge(color: AppColors.pureWhite),
                    ),
                    Text(
                      'Task #${widget.taskId.substring(0, widget.taskId.length > 8 ? 8 : widget.taskId.length)}',
                      style: AppTypography.labelSmall(color: AppColors.textTertiary),
                    ),
                  ],
                ),
              ),
              _buildStatusPill(_currentStatus),
            ],
          ),

          const SizedBox(height: AppSpacing.space16),

          // Progress indicator & percent
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    _statusMessage ?? _getStatusMessage(_currentStatus),
                    style: AppTypography.bodySmall(color: AppColors.textSecondary),
                  ),
                  Text(
                    '$_progress%',
                    style: AppTypography.labelSmall(
                      color: AppColors.pureWhite,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.space8),
              ClipRRect(
                borderRadius: BorderRadius.circular(AppRadii.pill),
                child: LinearProgressIndicator(
                  value: _progress / 100.0,
                  backgroundColor: AppColors.graphite,
                  valueColor: const AlwaysStoppedAnimation<Color>(AppColors.pureWhite),
                  minHeight: 6,
                ),
              ),
            ],
          ),

          const SizedBox(height: AppSpacing.space16),

          // Steps List
          ..._steps.map((step) => _buildStepRow(step)),

          // Action button if waiting for user
          if (isWaitingForUser) ...[
            const SizedBox(height: AppSpacing.space16),
            SizedBox(
              height: AppChrome.compactCircle,
              child: ElevatedButton.icon(
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.pureWhite,
                  foregroundColor: AppColors.pitchBlack,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(AppRadii.button),
                  ),
                ),
                icon: const Icon(Icons.key, size: 16),
                label: Text(
                  'Provide Secure Input',
                  style: AppTypography.labelMedium(
                    color: AppColors.pitchBlack,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                onPressed: _handleProvideInput,
              ),
            ),
          ],

          // Action button if completed
          if (isCompleted) ...[
            const SizedBox(height: AppSpacing.space16),
            SizedBox(
              height: AppChrome.compactCircle,
              child: OutlinedButton.icon(
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.pureWhite,
                  side: const BorderSide(color: AppColors.pureWhite, width: 1.0),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(AppRadii.button),
                  ),
                ),
                icon: const Icon(Icons.folder_open, size: 16),
                label: Text(
                  'View Document in Vault',
                  style: AppTypography.labelMedium(
                    color: AppColors.pureWhite,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                onPressed: widget.onNavigateToVault,
              ),
            ),
          ],

          if (isFailed) ...[
            const SizedBox(height: AppSpacing.space12),
            Container(
              padding: const EdgeInsets.all(AppSpacing.space8),
              decoration: BoxDecoration(
                color: AppColors.graphite,
                borderRadius: BorderRadius.circular(AppRadii.sm),
                border: Border.all(color: AppColors.borderWhite, width: 1.0),
              ),
              child: Row(
                children: [
                  const Icon(Icons.error_outline, size: 16, color: AppColors.pureWhite),
                  const SizedBox(width: AppSpacing.space8),
                  Expanded(
                    child: Text(
                      'Task halted. Policy or service error encountered.',
                      style: AppTypography.bodySmall(color: AppColors.pureWhite),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildStepRow(TaskStepItem step) {
    Widget icon;
    Color textColor;

    switch (step.status) {
      case 'completed':
        icon = const Icon(Icons.check_circle, size: 16, color: AppColors.pureWhite);
        textColor = AppColors.pureWhite;
        break;
      case 'running':
        icon = const SizedBox(
          width: 14,
          height: 14,
          child: CircularProgressIndicator(
            strokeWidth: 2,
            valueColor: AlwaysStoppedAnimation<Color>(AppColors.pureWhite),
          ),
        );
        textColor = AppColors.pureWhite;
        break;
      case 'failed':
        icon = const Icon(Icons.cancel_outlined, size: 16, color: AppColors.textSecondary);
        textColor = AppColors.textSecondary;
        break;
      case 'pending':
      default:
        icon = Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.all(color: AppColors.textTertiary, width: 1.5),
          ),
        );
        textColor = AppColors.textTertiary;
        break;
    }

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.space4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          SizedBox(
            width: 20,
            child: Center(child: icon),
          ),
          const SizedBox(width: AppSpacing.space12),
          Expanded(
            child: Text(
              step.title,
              style: AppTypography.bodySmall(
                color: textColor,
                fontWeight: step.status == 'running' ? FontWeight.w600 : FontWeight.w400,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusPill(String status) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.space8,
        vertical: AppSpacing.space2,
      ),
      decoration: BoxDecoration(
        color: AppColors.pitchBlack,
        borderRadius: BorderRadius.circular(AppRadii.pill),
        border: Border.all(color: AppColors.borderWhite, width: 1.0),
      ),
      child: Text(
        status,
        style: AppTypography.labelSmall(
          color: AppColors.pureWhite,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }

  String _getWorkflowTitle(String workflow) {
    switch (workflow) {
      case 'download_eaadhaar':
        return 'Download Masked e-Aadhaar';
      case 'check_status':
        return 'Aadhaar Status Inquiry';
      case 'update_address':
        return 'Address Update Workflow';
      default:
        return 'Service Automation';
    }
  }

  String _getStatusMessage(String status) {
    switch (status) {
      case 'RECEIVED':
        return 'Task queued...';
      case 'VALIDATING':
        return 'Validating parameters...';
      case 'PLANNING':
        return 'Planning execution steps...';
      case 'RUNNING':
        return 'Executing workflow...';
      case 'WAITING_FOR_USER':
        return 'Awaiting required user input';
      case 'AUTHENTICATING':
        return 'Authenticating credentials...';
      case 'DOWNLOADING':
        return 'Downloading document from portal...';
      case 'VERIFYING':
        return 'Verifying integrity & checksum...';
      case 'COMPLETED':
        return 'Task completed successfully';
      case 'FAILED':
        return 'Task encountered an error';
      default:
        return 'Processing...';
    }
  }
}
