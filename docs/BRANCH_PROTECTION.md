# Branch Protection Rules

## Main Branch Protection

Configure on GitHub: Settings → Branches → Branch protection rules

### Required Settings

**Require pull request reviews:**
- Required approving reviews: 1
- Dismiss stale reviews: Yes
- Require review from Code Owners: No

**Require status checks:**
- Require branches to be up to date: Yes
- Status checks that are required:
  - test (Python 3.11)
  - test (Python 3.12)
  - lint
  - type-check
  - verification
  - security

**Require conversation resolution:**
- Yes

**Do not allow bypassing:**
- Include administrators: Yes

### Quality Gates

**Coverage threshold:** 60% minimum
**All tests must pass**
**No linting errors**
**No type errors**
**Security scan must pass**

## Develop Branch Protection

Same as main but:
- Required approving reviews: 0 (optional)
- Allow force pushes: Yes (for rebasing)

## Setup Instructions

1. Go to your GitHub repository
2. Navigate to Settings → Branches
3. Click "Add branch protection rule"
4. Enter branch name pattern: `main`
5. Configure settings as listed above
6. Click "Create" or "Save changes"
7. Repeat for `develop` branch with modified settings

## Enforcement

All PRs to protected branches must:
- Pass all required status checks
- Have required number of approvals
- Resolve all conversations
- Be up to date with base branch

Administrators are also subject to these rules to ensure consistency and quality.
