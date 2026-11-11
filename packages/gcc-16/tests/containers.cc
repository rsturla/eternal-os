#include <algorithm>
#include <cassert>
#include <future>
#include <iostream>
#include <map>
#include <numeric>
#include <stdexcept>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
int main() {
  std::vector<int> v{4, 1, 3, 2};
  std::sort(v.begin(), v.end());
  assert(std::accumulate(v.begin(), v.end(), 0) == 10);
  std::map<std::string, int> m{{"answer", 42}};
  assert(m.at("answer") == 42);
  bool caught = false;
  try {
    throw std::runtime_error("unwind");
  } catch (const std::exception &e) {
    caught = std::string(e.what()) == "unwind";
  }
  assert(caught);
  auto f = std::async(std::launch::async, [] { return 42; });
  assert(f.get() == 42);
  std::ostringstream rendered;
  rendered << "answer=" << m.at("answer");
  assert(rendered.str() == "answer=42");
  std::cout << "cxx-runtime-ok\n";
  assert(std::cout.good());
}
