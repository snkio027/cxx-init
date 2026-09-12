// Formatting-only input: header names exercise grouping, not build dependencies.
#include "detail/config.hpp"
#include <fmt/format.h>
#include <vector>
#include "house_style.hpp"
#include <concepts>
#include <string_view>

namespace house_style {
struct EmptyTag {};
enum class State { idle, active, stopped };

template<typename T> concept Reader=requires(T &source) {
{source.read()}->std::same_as<int>;
};

template<typename T> requires Reader<T>
int read_one(T &source) noexcept {return source.read();}

class Window {
public:
Window(const int *first,const int *last):first_(first),last_(last){}
const int *data() const noexcept {return first_;}

private:
const int *first_;
const int *last_;
};

void publish_window(const Window &window, std::string_view destination_name, std::string_view transport_name, unsigned retry_budget) noexcept;

int process(std::vector<int> &values, int *result, const int &limit, Window &&window) {
int count=0; // First counter.
int total=0; // Second counter.
for(int value:values) total+=value;
while(count<limit) ++count;
if(total>limit) total=limit;
switch(count) {
case 0: total=0; break;
default: break;
}
auto positive=std::ranges::find_if(values,[](int value){return value>0;});
auto accumulate=[&](int value){total+=value; ++count;};
publish_window(window,"telemetry/main/diagnostics/status","reliable-streaming-transport",static_cast<unsigned>(count));
*result=total;
return count;
}

const char *message="This intentionally long human-facing message must remain a single string literal instead of being split to meet the column limit.";
}
