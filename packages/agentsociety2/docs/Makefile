# Minimal makefile for Sphinx documentation
#

# You can set these variables from the command line, and also
# from the environment for the first two.
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SPHINXINTL    ?= sphinx-intl
SOURCEDIR     = .
BUILDDIR      = _build

# Put it first so that "make" without argument is like "make help".
help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help Makefile gettext update-po build-po html-zh html-en html-all

# 国际化相关命令

# 提取需要翻译的文本
gettext:
	@echo "提取可翻译的文本..."
	$(SPHINXBUILD) -b gettext $(SPHINXOPTS) $(SOURCEDIR) $(BUILDDIR)/gettext

# 更新翻译文件
# Keep committed source locations relative to docs/_build/gettext.
update-po: override BUILDDIR := $(SOURCEDIR)/_build
update-po: gettext
	@echo "更新翻译文件..."
	$(SPHINXINTL) update -p $(BUILDDIR)/gettext -d $(SOURCEDIR)/locale -l en

# 编译翻译文件
build-po:
	@echo "编译翻译文件..."
	$(SPHINXINTL) build -d $(SOURCEDIR)/locale

# 构建中文文档（默认）
html-zh:
	@echo "构建中文文档..."
	$(SPHINXBUILD) -b html -D language=zh $(SPHINXOPTS) $(SOURCEDIR) $(BUILDDIR)/html/zh

# 构建英文文档
html-en: build-po
	@echo "构建英文文档..."
	$(SPHINXBUILD) -b html -D language=en $(SPHINXOPTS) $(SOURCEDIR) $(BUILDDIR)/html/en

# 构建所有语言版本
html-all: html-zh html-en
	@echo "所有语言版本构建完成！"

# 默认构建中文版本
html: html-zh

# 清理构建文件
clean:
	@echo "清理构建文件..."
	rm -rf $(BUILDDIR)/*

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
