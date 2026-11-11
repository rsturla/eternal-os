assert(_VERSION == 'Lua 5.4')
local values = {3, 1, 2}
table.sort(values)
assert(table.concat(values, ',') == '1,2,3')
assert(('hello 42'):match('%d+') == '42')
assert(utf8.len('é☃') == 2)

local co = coroutine.create(function(x)
    coroutine.yield(x + 1)
    return x + 2
end)
local ok, value = coroutine.resume(co, 40)
assert(ok and value == 41)
ok, value = coroutine.resume(co)
assert(ok and value == 42)

local mt = {__add = function(a, b) return a.v + b.v end}
assert(setmetatable({v = 20}, mt) + setmetatable({v = 22}, mt) == 42)
local succeeded, message = pcall(function() error('expected') end)
assert(not succeeded and message:match('expected'))
local fn = assert(load(string.dump(function(x) return x * 2 end)))
assert(fn(21) == 42)

local file = assert(io.open('payload', 'wb'))
assert(file:write('binary\0payload'))
assert(file:close())
file = assert(io.open('payload', 'rb'))
assert(file:read('a') == 'binary\0payload')
assert(file:close())
assert(os.remove('payload'))
collectgarbage('collect')
