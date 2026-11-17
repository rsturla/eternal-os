project('eternal-probe', 'c', version: '1.0')
lib = shared_library('answer', 'answer.c', install: true)
exe = executable('probe', 'main.c', link_with: lib, install: true)
test('runtime', exe)
