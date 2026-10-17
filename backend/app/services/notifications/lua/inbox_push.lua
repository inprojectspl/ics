-- Append one notification to a user's inbox (ADR-0023, section 5).
-- KEYS: log (stream), unread (zset), ck (collapse pointer)
-- ARGV: payload json, cap, min id, key ttl, collapse ttl, collapse flag
-- Returns {new id, unread count}.
local log, unread, ck = KEYS[1], KEYS[2], KEYS[3]
local payload = ARGV[1]
local cap = tonumber(ARGV[2])
local min_id = ARGV[3]
local ttl = tonumber(ARGV[4])
local ck_ttl = tonumber(ARGV[5])
local collapse = ARGV[6] == '1'

local function parse(id)
  local ms, seq = string.match(id, '^(%d+)-(%d+)$')
  return tonumber(ms), tonumber(seq)
end

local function older(a, b)
  local ams, aseq = parse(a)
  local bms, bseq = parse(b)
  return ams < bms or (ams == bms and aseq < bseq)
end

if collapse then
  local old = redis.call('GET', ck)
  -- A read entry is never merged: an item the user has seen must not change.
  if old and redis.call('ZSCORE', unread, old) then
    local rows = redis.call('XRANGE', log, old, old)
    if #rows > 0 then
      local prev = cjson.decode(rows[1][2][2])
      local cur = cjson.decode(payload)
      cur['n'] = (prev['n'] or 1) + (cur['n'] or 1)
      local pf = prev['fv'] or prev['v']
      local cf = cur['fv'] or cur['v']
      if type(pf) == 'number' and type(cf) == 'number' then
        cur['fv'] = math.min(pf, cf)
      end
      payload = cjson.encode(cur)
    end
    redis.call('XDEL', log, old)
    redis.call('ZREM', unread, old)
  end
end

local id = redis.call('XADD', log, '*', 'p', payload)
local ms = parse(id)
redis.call('ZADD', unread, ms, id)
if collapse then
  redis.call('SET', ck, id, 'EX', ck_ttl)
end

local trimmed = redis.call('XTRIM', log, 'MINID', min_id)
  + redis.call('XTRIM', log, 'MAXLEN', cap)
-- Unread ids must stay a subset of the log, so the count is ZCARD. Only a
-- trim can break that, so the clean-up runs only after one.
local oldest = trimmed > 0 and redis.call('XRANGE', log, '-', '+', 'COUNT', 1) or nil
if oldest == nil then
  -- nothing trimmed
elseif #oldest == 0 then
  redis.call('DEL', unread)
else
  local oid = oldest[1][1]
  local oms = parse(oid)
  for _, member in ipairs(redis.call('ZRANGEBYSCORE', unread, '-inf', oms)) do
    if older(member, oid) then
      redis.call('ZREM', unread, member)
    end
  end
end

redis.call('EXPIRE', log, ttl)
redis.call('EXPIRE', unread, ttl)
return {id, redis.call('ZCARD', unread)}
