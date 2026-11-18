#include <cmath>
import "math-header.hh";

int main(int argc, char** argv) {
    if (argc != 2 || argv[1][0] == '\0')
        return 2;
    double value = 0;
    for (const char* digit = argv[1]; *digit; ++digit) {
        if (*digit < '0' || *digit > '9')
            return 2;
        value = value * 10 + (*digit - '0');
    }
    // The argument reaches sqrt at runtime, including in optimized builds.
    volatile double input = value;
    return std::sqrt(input) == 9.0 ? 0 : 1;
}
