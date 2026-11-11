#include <libdnf5/base/base.hpp>
#include <libdnf5/conf/config_main.hpp>

#include <cassert>

int main() {
  libdnf5::Base base;
  assert(!base.is_initialized());
  auto &config = base.get_config();
  config.get_plugins_option().set(false);
  config.get_cachedir_option().set("/tmp/rpmx-libdnf-cache");
  assert(!config.get_plugins_option().get_value());
  assert(config.get_cachedir_option().get_value() == "/tmp/rpmx-libdnf-cache");
}
