cmake_minimum_required(VERSION 3.20)
project(bb10_volte_mobile LANGUAGES CXX)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/arm/o.le-v7-g")
set(BB10_MOBILE_VERSION "0.1.0.15" CACHE STRING "Mobile release version")
set(BB10_PUBLIC_KEY_ID "unconfigured" CACHE STRING "Product signing key identifier")
option(BB10_ALLOW_INCOMPLETE_BUNDLE "Compile UI only; runtime remains disabled" OFF)
set(BB10_ENTRY_SHA256 "")
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/assets/runtime/entry.py")
    file(SHA256 "${CMAKE_CURRENT_SOURCE_DIR}/assets/runtime/entry.py" BB10_ENTRY_SHA256)
elseif(NOT BB10_ALLOW_INCOMPLETE_BUNDLE)
    message(FATAL_ERROR "Missing verified runtime bundle. Run tools/build_mobile.py; UI-only compile requires BB10_ALLOW_INCOMPLETE_BUNDLE=ON.")
endif()
configure_file(src/bundle_identity.h.in "${CMAKE_CURRENT_BINARY_DIR}/generated/bundle_identity.h" @ONLY)

include(BB10Qt4)
qt4_wrap_cpp(MOC_SOURCES src/mobilecontroller.h src/supportcontroller.h)
add_executable(bb10volte src/main.cpp src/mobilecontroller.cpp src/supportcontroller.cpp ${MOC_SOURCES})
target_include_directories(bb10volte PRIVATE src "${CMAKE_CURRENT_BINARY_DIR}/generated")
target_link_libraries(bb10volte PRIVATE
    bbcascades bbdata bbsystem bbcascadespickers
    QtDeclarative QtScript QtSvg QtSql sqlite3 z QtXmlPatterns
    QtGui QtNetwork socket QtCore crypto)
