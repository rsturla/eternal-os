#include <assert.h>
#include <string.h>
#include <blkid/blkid.h>
#include <libfdisk/libfdisk.h>
#include <libmount/libmount.h>
#include <libsmartcols/libsmartcols.h>
#include <uuid/uuid.h>

int main(void)
{
    blkid_probe probe = blkid_new_probe();
    assert(probe);
    blkid_free_probe(probe);

    struct fdisk_context *disk = fdisk_new_context();
    assert(disk);
    fdisk_unref_context(disk);

    struct libmnt_table *mounts = mnt_new_table();
    assert(mounts);
    mnt_unref_table(mounts);

    struct libscols_table *columns = scols_new_table();
    assert(columns);
    scols_unref_table(columns);

    const char *text = "00112233-4455-6677-8899-aabbccddeeff";
    uuid_t uuid;
    char formatted[37];
    assert(uuid_parse(text, uuid) == 0);
    uuid_unparse_lower(uuid, formatted);
    assert(strcmp(text, formatted) == 0);
    return 0;
}
