PROJECT_NAME=apicache
TAG?=$(shell git describe --tags)

clean:
	rm -drf dist

build/library: clean
	python3 -m build --sdist
