.DELETE_ON_ERROR:
.PHONY: all clean expected-failure
all: result
result: input
	cat $< > $@
	printf ' suffix' >> $@
	printf x >> count
broken:
	printf partial > $@
	false
expected-failure: broken
clean:
	rm -f result count
