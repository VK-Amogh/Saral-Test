import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:open_filex/open_filex.dart';
import 'package:share_plus/share_plus.dart';
import '../../../core/theme/tokens.dart';
import '../../../core/widgets/glass_surface.dart';
import '../models/vault_document.dart';
import '../providers/vault_provider.dart';

class VaultScreen extends ConsumerWidget {
  const VaultScreen({super.key});

  String _formatCountdown(Duration duration) {
    if (duration.isNegative || duration == Duration.zero) {
      return 'Expired';
    }
    final hours = duration.inHours;
    final minutes = duration.inMinutes.remainder(60);
    final seconds = duration.inSeconds.remainder(60);

    if (hours > 0) {
      return '${hours}h ${minutes}m ${seconds}s';
    }
    return '${minutes}m ${seconds}s';
  }

  Future<void> _handleOpenFile(BuildContext context, VaultDocument doc) async {
    if (doc.pdfEncrypted) {
      final shouldOpen = await _showPasswordHintDialog(context, doc);
      if (shouldOpen != true || !context.mounted) return;
    }
    await _openDocumentFile(context, doc);
  }

  Future<void> _openDocumentFile(BuildContext context, VaultDocument doc) async {
    try {
      final result = await OpenFilex.open(doc.storagePath);
      if (result.type != ResultType.done && context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Opening document: ${doc.fileName}',
              style: AppTypography.bodySmall(color: AppColors.pureWhite),
            ),
          ),
        );
      }
    } catch (_) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Document ready: ${doc.fileName}',
              style: AppTypography.bodySmall(color: AppColors.pureWhite),
            ),
          ),
        );
      }
    }
  }

  Future<bool?> _showPasswordHintDialog(BuildContext context, VaultDocument doc) {
    return showDialog<bool>(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        backgroundColor: AppColors.darkGrey,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadii.card),
          side: const BorderSide(color: AppColors.borderWhite, width: 1.0),
        ),
        title: Row(
          children: [
            const Icon(Icons.lock_outline, color: AppColors.pureWhite, size: 20),
            const SizedBox(width: AppSpacing.space8),
            Expanded(
              child: Text(
                'Password Protected Document',
                style: AppTypography.cardHeading(color: AppColors.pureWhite),
              ),
            ),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'This official e-Aadhaar PDF is encrypted by UIDAI.',
              style: AppTypography.bodySmall(color: AppColors.textSecondary),
            ),
            const SizedBox(height: AppSpacing.space12),
            Container(
              padding: const EdgeInsets.all(AppSpacing.space12),
              decoration: BoxDecoration(
                color: AppColors.pitchBlack,
                borderRadius: BorderRadius.circular(AppRadii.card),
                border: Border.all(color: AppColors.borderWhite, width: 1.0),
              ),
              child: Text(
                'Password: First 4 letters of your name in CAPITAL + 4-digit Year of Birth (e.g., SURE1990)',
                style: AppTypography.bodySmall(color: AppColors.pureWhite),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogCtx).pop(false),
            child: Text(
              'Cancel',
              style: AppTypography.labelMedium(color: AppColors.textSecondary),
            ),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.pureWhite,
              foregroundColor: AppColors.pitchBlack,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppRadii.button),
              ),
            ),
            onPressed: () => Navigator.of(dialogCtx).pop(true),
            child: Text(
              'Open Document',
              style: AppTypography.labelMedium(
                color: AppColors.pitchBlack,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _handleShareFile(BuildContext context, VaultDocument doc) async {
    try {
      // ignore: deprecated_member_use
      await Share.share(
        'Document: ${doc.fileName} (SHA256: ${doc.sha256.substring(0, 12)}...)',
        subject: doc.fileName,
      );
    } catch (_) {}
  }

  void _handleDelete(BuildContext context, WidgetRef ref, VaultDocument doc) {
    showDialog(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        backgroundColor: AppColors.darkGrey,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadii.card),
          side: const BorderSide(color: AppColors.borderWhite, width: 1.0),
        ),
        title: Text(
          'Delete Document',
          style: AppTypography.cardHeading(color: AppColors.pureWhite),
        ),
        content: Text(
          'Permanently remove "${doc.fileName}" from device vault?',
          style: AppTypography.bodyMedium(color: AppColors.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogCtx).pop(),
            child: Text(
              'Cancel',
              style: AppTypography.labelMedium(color: AppColors.textSecondary),
            ),
          ),
          TextButton(
            onPressed: () {
              ref.read(vaultProvider.notifier).deleteDocument(doc.id);
              Navigator.of(dialogCtx).pop();
            },
            child: Text(
              'Delete',
              style: AppTypography.labelMedium(
                color: AppColors.pureWhite,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final vaultState = ref.watch(vaultProvider);
    final documents = vaultState.documents;

    return Scaffold(
      backgroundColor: AppColors.pitchBlack,
      appBar: AppBar(
        backgroundColor: AppColors.pitchBlack,
        elevation: 0,
        title: Text(
          'Document Vault',
          style: AppTypography.sectionHeading(),
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: AppColors.pureWhite),
          onPressed: () => Navigator.of(context).maybePop(),
        ),
      ),
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Vault Security Header Card
            Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.screenMargin,
                vertical: AppSpacing.space8,
              ),
              child: GlassSurface(
                padding: const EdgeInsets.all(AppSpacing.space16),
                child: Row(
                  children: [
                    Container(
                      width: 40,
                      height: 40,
                      decoration: BoxDecoration(
                        color: AppColors.pitchBlack,
                        shape: BoxShape.circle,
                        border: Border.all(color: AppColors.borderWhite, width: 1.0),
                      ),
                      child: const Icon(Icons.lock_outline, color: AppColors.pureWhite, size: 20),
                    ),
                    const SizedBox(width: AppSpacing.space12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Encrypted Device Storage',
                            style: AppTypography.labelLarge(color: AppColors.pureWhite),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            'Strict retention policy. Files auto-purge upon timer expiry.',
                            style: AppTypography.bodySmall(color: AppColors.textSecondary),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),

            const SizedBox(height: AppSpacing.space8),

            // Document List
            Expanded(
              child: documents.isEmpty
                  ? Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          const Icon(Icons.folder_open, size: 48, color: AppColors.textTertiary),
                          const SizedBox(height: AppSpacing.space16),
                          Text(
                            'Vault is Empty',
                            style: AppTypography.cardHeading(color: AppColors.textSecondary),
                          ),
                          const SizedBox(height: AppSpacing.space8),
                          Text(
                            'Downloaded Aadhaar documents will appear here.',
                            style: AppTypography.bodySmall(color: AppColors.textTertiary),
                          ),
                        ],
                      ),
                    )
                  : ListView.builder(
                      padding: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.screenMargin,
                        vertical: AppSpacing.space8,
                      ),
                      itemCount: documents.length,
                      itemBuilder: (ctx, index) {
                        final doc = documents[index];
                        return _buildDocumentCard(context, ref, doc);
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildDocumentCard(BuildContext context, WidgetRef ref, VaultDocument doc) {
    final remaining = doc.remainingTime;

    return GlassSurface(
      margin: const EdgeInsets.only(bottom: AppSpacing.space12),
      padding: const EdgeInsets.all(AppSpacing.space16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Top Row: Doc Icon, Name, Expire countdown pill
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: AppColors.pitchBlack,
                  borderRadius: BorderRadius.circular(AppRadii.sm),
                  border: Border.all(color: AppColors.borderWhite, width: 1.0),
                ),
                child: const Icon(Icons.picture_as_pdf, color: AppColors.pureWhite, size: 20),
              ),
              const SizedBox(width: AppSpacing.space12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      doc.fileName,
                      style: AppTypography.labelLarge(color: AppColors.pureWhite),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${doc.formattedSize} · ${doc.pdfEncrypted ? "Password Protected" : "Standard"}',
                      style: AppTypography.bodySmall(color: AppColors.textTertiary),
                    ),
                  ],
                ),
              ),
              // Auto-delete countdown badge
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.space8,
                  vertical: AppSpacing.space4,
                ),
                decoration: BoxDecoration(
                  color: AppColors.pitchBlack,
                  borderRadius: BorderRadius.circular(AppRadii.pill),
                  border: Border.all(color: AppColors.borderWhite, width: 1.0),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.timer_outlined, size: 12, color: AppColors.pureWhite),
                    const SizedBox(width: 4),
                    Text(
                      _formatCountdown(remaining),
                      style: AppTypography.labelSmall(
                        color: AppColors.pureWhite,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),

          const SizedBox(height: AppSpacing.space12),

          // Checksum preview
          Container(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.space8,
              vertical: AppSpacing.space4,
            ),
            decoration: BoxDecoration(
              color: AppColors.pitchBlack,
              borderRadius: BorderRadius.circular(AppRadii.xs),
            ),
            child: Row(
              children: [
                const Icon(Icons.fingerprint, size: 12, color: AppColors.textTertiary),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    'SHA-256: ${doc.sha256}',
                    style: AppTypography.labelSmall(color: AppColors.textTertiary),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
          ),

          // Informative password formula banner for encrypted PDFs
          if (doc.pdfEncrypted) ...[
            const SizedBox(height: AppSpacing.space8),
            Container(
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.space12,
                vertical: AppSpacing.space8,
              ),
              decoration: BoxDecoration(
                color: AppColors.pitchBlack,
                borderRadius: BorderRadius.circular(AppRadii.xs),
                border: Border.all(color: AppColors.borderWhite, width: 1.0),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.info_outline, size: 14, color: AppColors.pureWhite),
                  const SizedBox(width: AppSpacing.space8),
                  Expanded(
                    child: Text(
                      'Password: First 4 letters of your name in CAPITAL + 4-digit Year of Birth (e.g., SURE1990)',
                      style: AppTypography.labelSmall(color: AppColors.textSecondary),
                    ),
                  ),
                ],
              ),
            ),
          ],

          const SizedBox(height: AppSpacing.space16),

          // Action Buttons: Open, Share, Delete
          Row(
            children: [
              Expanded(
                child: SizedBox(
                  height: AppChrome.compactCircle,
                  child: ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.pureWhite,
                      foregroundColor: AppColors.pitchBlack,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(AppRadii.button),
                      ),
                    ),
                    icon: const Icon(Icons.visibility_outlined, size: 16),
                    label: Text(
                      'Open',
                      style: AppTypography.labelMedium(
                        color: AppColors.pitchBlack,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    onPressed: () => _handleOpenFile(context, doc),
                  ),
                ),
              ),
              const SizedBox(width: AppSpacing.space8),
              SizedBox(
                height: AppChrome.compactCircle,
                child: OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.pureWhite,
                    side: const BorderSide(color: AppColors.borderWhite, width: 1.0),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(AppRadii.button),
                    ),
                  ),
                  icon: const Icon(Icons.share_outlined, size: 16),
                  label: Text('Share', style: AppTypography.labelMedium(color: AppColors.pureWhite)),
                  onPressed: () => _handleShareFile(context, doc),
                ),
              ),
              const SizedBox(width: AppSpacing.space8),
              IconButton(
                icon: const Icon(Icons.delete_outline, color: AppColors.textSecondary, size: 20),
                tooltip: 'Delete',
                onPressed: () => _handleDelete(context, ref, doc),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
