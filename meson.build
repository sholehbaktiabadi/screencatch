project(
  'screencatch',
  version: '1.0.0',
  license: 'MIT',
  meson_version: '>= 0.62.0',
)

app_id = 'io.github.sholehbaktiabadi.ScreenCatch'

python = import('python')
gnome = import('gnome')
py = python.find_installation('python3')

prefix = get_option('prefix')
bindir = prefix / get_option('bindir')
datadir = prefix / get_option('datadir')
pkgdatadir = datadir / meson.project_name()

conf = configuration_data()
conf.set('PYTHON', py.full_path())
conf.set('PKGDATADIR', pkgdatadir)
conf.set('DATADIR', datadir)

configure_file(
  input: 'bin/screencatch.in',
  output: 'screencatch',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)

subdir('src')
subdir('data')
subdir('tests')

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
