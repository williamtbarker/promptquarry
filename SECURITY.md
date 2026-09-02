# Security policy

## Reporting

Use GitHub's private vulnerability reporting feature rather than a public issue. Include a
minimal synthetic reproducer and the affected command.

Do not attach conversation exports, extracted code, credentials, personal paths, or other private
material to a report.

## Trust boundary

PromptQuarry treats archives and recovered code as untrusted data. It does not execute extracted
code. Its sensitivity rules assist human review but are not a secret scanner or a guarantee that
content is safe to publish. Run the tool locally, protect its SQLite database and output, and
inspect every candidate before using or sharing it.
