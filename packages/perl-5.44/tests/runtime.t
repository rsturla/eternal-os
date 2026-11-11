use strict;
use warnings;
use Test::More;
use JSON::PP;
use MIME::Base64;
use Digest::SHA qw(sha256_hex);
use IO::Compress::Gzip qw(gzip);
use IO::Uncompress::Gunzip qw(gunzip);
use IO::Compress::Bzip2 qw(bzip2);
use IO::Uncompress::Bunzip2 qw(bunzip2);
use Storable qw(freeze thaw);

is(sha256_hex('abc'),
   'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
   'SHA256 known vector');
my $value = {answer => 42, values => [1, 2, 3]};
is_deeply(decode_json(encode_json($value)), $value, 'JSON roundtrip');
is_deeply(thaw(freeze($value)), $value, 'Storable roundtrip');
my $payload = join('', map chr, 0..255) x 100;
is(decode_base64(encode_base64($payload)), $payload, 'base64 binary roundtrip');

my ($packed, $unpacked);
ok(gzip(\$payload => \$packed), 'gzip compression');
ok(gunzip(\$packed => \$unpacked), 'gzip decompression');
is($unpacked, $payload, 'gzip roundtrip');
ok(bzip2(\$payload => \$packed), 'bzip2 compression');
ok(bunzip2(\$packed => \$unpacked), 'bzip2 decompression');
is($unpacked, $payload, 'bzip2 roundtrip');
my @numbers = sort {$a <=> $b} (4, 1, 3, 2);
is_deeply(\@numbers, [1, 2, 3, 4], 'numeric sorting');
eval {die "expected"};
like($@, qr/expected/, 'exception');

open my $file, '>', 'payload' or die $!;
print $file '42';
close $file or die $!;
open $file, '<', 'payload' or die $!;
is(<$file>, '42', 'file IO');
close $file or die $!;
done_testing;
