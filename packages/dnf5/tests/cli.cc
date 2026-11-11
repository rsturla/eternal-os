#include <libdnf5-cli/argument_parser.hpp>
#include <libdnf5/conf/option_string.hpp>

#include <cassert>

int main() {
  libdnf5::cli::ArgumentParser parser;
  auto *root = parser.add_new_command("probe");
  parser.set_root_command(root);
  libdnf5::OptionString value("unset");
  auto *answer = parser.add_new_named_arg("answer");
  answer->set_long_name("answer");
  answer->set_has_value(true);
  answer->link_value(&value);
  root->register_named_arg(answer);
  const char *arguments[] = {"probe", "--answer", "42"};
  parser.parse(3, arguments);
  assert(value.get_value() == "42");
  assert(answer->get_parse_count() == 1);
  parser.reset_parse_count();
  assert(answer->get_parse_count() == 0);
  const char *invalid[] = {"probe", "--missing"};
  try {
    parser.parse(2, invalid);
  } catch (const libdnf5::cli::ArgumentParserUnknownArgumentError &) {
    return 0;
  }
  return 1;
}
