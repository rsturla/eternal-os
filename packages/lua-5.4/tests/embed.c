#include <lauxlib.h>
#include <lua.h>
#include <lualib.h>
int main(void) {
  lua_State *L = luaL_newstate();
  if (!L)
    return 1;
  luaL_openlibs(L);
  if (luaL_dostring(L, "return math.floor(42.9)"))
    return 2;
  int result = lua_tointeger(L, -1) != 42;
  lua_close(L);
  return result;
}
