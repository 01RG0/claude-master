//go:build windows

package gateway

import (
	"fmt"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	crypt32                = windows.NewLazySystemDLL("crypt32.dll")
	procProtectData        = crypt32.NewProc("CryptProtectData")
	procUnprotectData      = crypt32.NewProc("CryptUnprotectData")
	kernel32               = windows.NewLazySystemDLL("kernel32.dll")
	procLocalFree          = kernel32.NewProc("LocalFree")
)

type dataBlob struct {
	cbData uint32
	pbData *byte
}

func protectPlatform(plain []byte) ([]byte, error) {
	if len(plain) == 0 {
		return nil, fmt.Errorf("empty secret")
	}
	in := dataBlob{cbData: uint32(len(plain)), pbData: &plain[0]}
	var out dataBlob
	r, _, err := procProtectData.Call(
		uintptr(unsafe.Pointer(&in)),
		uintptr(0), // description
		uintptr(0), // entropy
		uintptr(0), // reserved
		uintptr(0), // prompt struct
		uintptr(0), // flags: CURRENT_USER
		uintptr(unsafe.Pointer(&out)),
	)
	if r == 0 {
		return nil, fmt.Errorf("CryptProtectData: %v", err)
	}
	defer procLocalFree.Call(uintptr(unsafe.Pointer(out.pbData)))
	buf := make([]byte, out.cbData)
	copy(buf, unsafe.Slice(out.pbData, out.cbData))
	return buf, nil
}

func unprotectPlatform(blob []byte) ([]byte, error) {
	if len(blob) == 0 {
		return nil, fmt.Errorf("empty blob")
	}
	in := dataBlob{cbData: uint32(len(blob)), pbData: &blob[0]}
	var out dataBlob
	r, _, err := procUnprotectData.Call(
		uintptr(unsafe.Pointer(&in)),
		uintptr(0), uintptr(0), uintptr(0), uintptr(0),
		uintptr(0),
		uintptr(unsafe.Pointer(&out)),
	)
	if r == 0 {
		return nil, fmt.Errorf("CryptUnprotectData: %v", err)
	}
	defer procLocalFree.Call(uintptr(unsafe.Pointer(out.pbData)))
	buf := make([]byte, out.cbData)
	copy(buf, unsafe.Slice(out.pbData, out.cbData))
	return buf, nil
}
