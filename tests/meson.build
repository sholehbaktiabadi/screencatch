test(
  'unit-tests',
  py,
  args: ['-m', 'unittest', 'discover', '-s', meson.current_source_dir(), '-t', meson.project_source_root()],
  env: ['PYTHONPATH=' + (meson.project_source_root() / 'src'), 'PYTHONDONTWRITEBYTECODE=1'],
  timeout: 120,
)

test(
  'version-consistency',
  py,
  args: [meson.current_source_dir() / 'check_version.py', meson.project_version()],
  env: ['PYTHONPATH=' + (meson.project_source_root() / 'src'), 'PYTHONDONTWRITEBYTECODE=1'],
)
