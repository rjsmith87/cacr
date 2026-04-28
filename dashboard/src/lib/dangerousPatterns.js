// Client-side dangerous-pattern detector for the Router Playground.
// Mirrors router/complexity.py's _DANGEROUS regex with a few additions
// the user called out in the bug report (subprocess, base64+decode chains).
// Keep this list and complexity.py's _DANGEROUS in sync — they encode the
// same product judgement about what looks like security-sensitive code.

const DANGEROUS_PATTERNS = {
  'pickle deserialization': /\bpickle\s*\.\s*(loads?|dumps?)\b/i,
  'eval()': /\beval\s*\(/i,
  'exec()': /\bexec\s*\(/i,
  'os.system': /\bos\s*\.\s*system\b/i,
  'subprocess': /\bsubprocess\s*\.\s*(call|run|Popen|check_output)\b/i,
  '__import__': /\b__import__\s*\(/i,
  'yaml.load': /\byaml\s*\.\s*load\b/i,
  'shelve.open': /\bshelve\s*\.\s*open\b/i,
  'raw SQL with f-string': /f['"]\s*(SELECT|INSERT|UPDATE|DELETE)\b/i,
  'SQL string concatenation': /\+\s*['"][^'"]*\b(SELECT|INSERT|UPDATE|DELETE)\b/i,
  'base64 decode chain': /\bbase64\s*\.\s*\w*decode\b/i,
}

// Returns an array of human-readable pattern names found in `code`.
// Empty array means no dangerous patterns matched.
export function scanDangerousPatterns(code) {
  if (!code) return []
  const matches = []
  for (const [name, re] of Object.entries(DANGEROUS_PATTERNS)) {
    if (re.test(code)) matches.push(name)
  }
  return matches
}
