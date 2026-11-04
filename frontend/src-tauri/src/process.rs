//! Start the backend suspended, attach its entire process tree to a Job, then run.
use std::{
    collections::BTreeMap,
    ffi::{OsStr, OsString},
    fs::File,
    io,
    os::windows::{
        ffi::OsStrExt,
        io::{AsRawHandle, FromRawHandle, OwnedHandle},
    },
    path::Path,
    ptr,
};
use windows_sys::Win32::{
    Foundation::*,
    Security::SECURITY_ATTRIBUTES,
    System::{JobObjects::*, Pipes::CreatePipe, Threading::*},
};

fn wide(value: &OsStr) -> Vec<u16> {
    value.encode_wide().chain(Some(0)).collect()
}

fn quoted(value: &OsStr) -> Vec<u16> {
    let mut out = vec![b'"' as u16];
    let mut slashes = 0;
    for ch in value.encode_wide() {
        if ch == b'\\' as u16 {
            slashes += 1;
            continue;
        }
        out.extend(std::iter::repeat_n(
            b'\\' as u16,
            slashes * if ch == b'"' as u16 { 2 } else { 1 },
        ));
        if ch == b'"' as u16 {
            out.push(b'\\' as u16);
        }
        out.push(ch);
        slashes = 0;
    }
    out.extend(std::iter::repeat_n(b'\\' as u16, slashes * 2));
    out.push(b'"' as u16);
    out
}

pub struct BackendProcess {
    _job: OwnedHandle,
    process: OwnedHandle,
    stdin: Option<File>,
}

impl BackendProcess {
    pub fn spawn(
        exe: &Path,
        args: &[OsString],
        root: &Path,
        env: &[(&str, OsString)],
        log: &File,
    ) -> io::Result<(Self, File)> {
        unsafe {
            let raw_job = CreateJobObjectW(ptr::null(), ptr::null());
            if raw_job.is_null() {
                return Err(io::Error::last_os_error());
            }
            let job = OwnedHandle::from_raw_handle(raw_job);
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(
                raw_job,
                JobObjectExtendedLimitInformation,
                &limits as *const _ as _,
                std::mem::size_of_val(&limits) as u32,
            ) == 0
            {
                return Err(io::Error::last_os_error());
            }
            let security = SECURITY_ATTRIBUTES {
                nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
                lpSecurityDescriptor: ptr::null_mut(),
                bInheritHandle: 1,
            };
            let mut read = ptr::null_mut();
            let mut write = ptr::null_mut();
            if CreatePipe(&mut read, &mut write, &security, 0) == 0 {
                return Err(io::Error::last_os_error());
            }
            let stdout = File::from_raw_handle(read);
            let writer = OwnedHandle::from_raw_handle(write);
            if SetHandleInformation(read, HANDLE_FLAG_INHERIT, 0) == 0 {
                return Err(io::Error::last_os_error());
            }
            let mut input_read = ptr::null_mut();
            let mut input_write = ptr::null_mut();
            if CreatePipe(&mut input_read, &mut input_write, &security, 0) == 0 {
                return Err(io::Error::last_os_error());
            }
            let stdin = OwnedHandle::from_raw_handle(input_read);
            let input = File::from_raw_handle(input_write);
            if SetHandleInformation(input_write, HANDLE_FLAG_INHERIT, 0) == 0 {
                return Err(io::Error::last_os_error());
            }
            let stderr = log.try_clone()?;
            if SetHandleInformation(
                stderr.as_raw_handle(),
                HANDLE_FLAG_INHERIT,
                HANDLE_FLAG_INHERIT,
            ) == 0
            {
                return Err(io::Error::last_os_error());
            }
            let mut command = quoted(exe.as_os_str());
            for arg in args {
                command.push(b' ' as u16);
                command.extend(quoted(arg));
            }
            command.push(0);
            let mut environment: BTreeMap<OsString, OsString> = std::env::vars_os()
                .map(|(key, value)| {
                    (
                        OsString::from(key.to_string_lossy().to_ascii_uppercase()),
                        value,
                    )
                })
                .collect();
            for (key, value) in env {
                environment.insert(OsString::from(key), value.clone());
            }
            // Windows environment names are case-insensitive. Do not inherit Python injection paths.
            environment.retain(|key, _| {
                !matches!(
                    key.to_string_lossy().as_ref(),
                    "PYTHONHOME" | "PYTHONPATH" | "VIRTUAL_ENV"
                )
            });
            let mut block = Vec::new();
            for (key, value) in environment {
                block.extend(key.encode_wide());
                block.push(b'=' as u16);
                block.extend(value.encode_wide());
                block.push(0);
            }
            block.push(0);
            let mut startup: STARTUPINFOW = std::mem::zeroed();
            startup.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
            startup.dwFlags = STARTF_USESTDHANDLES;
            startup.hStdOutput = write;
            startup.hStdError = stderr.as_raw_handle();
            startup.hStdInput = stdin.as_raw_handle();
            let mut info: PROCESS_INFORMATION = std::mem::zeroed();
            let success = CreateProcessW(
                wide(exe.as_os_str()).as_ptr(),
                command.as_mut_ptr(),
                ptr::null(),
                ptr::null(),
                1,
                CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT,
                block.as_ptr() as _,
                wide(root.as_os_str()).as_ptr(),
                &startup,
                &mut info,
            );
            if success == 0 {
                return Err(io::Error::last_os_error());
            }
            let process = OwnedHandle::from_raw_handle(info.hProcess);
            let thread = OwnedHandle::from_raw_handle(info.hThread);
            if AssignProcessToJobObject(raw_job, info.hProcess) == 0 {
                let error = io::Error::last_os_error();
                TerminateProcess(info.hProcess, 1);
                return Err(error);
            }
            let owner = Self {
                _job: job,
                process,
                stdin: Some(input),
            };
            if ResumeThread(thread.as_raw_handle()) == u32::MAX {
                return Err(io::Error::last_os_error());
            }
            drop(writer);
            Ok((owner, stdout))
        }
    }

    pub fn wait(&self, milliseconds: u32) {
        unsafe {
            WaitForSingleObject(self.process.as_raw_handle(), milliseconds);
        }
    }

    pub fn download_models(&mut self, pause: bool) -> io::Result<()> {
        use std::io::Write;
        let stdin = self.stdin.as_mut().ok_or_else(|| io::Error::new(io::ErrorKind::BrokenPipe, "模型下载已结束。"))?;
        stdin.write_all(if pause { b"pause\n" } else { b"download\n" })?;
        stdin.flush()
    }

    pub fn finish_model_setup(&mut self) {
        self.stdin.take();
    }
}

pub fn show_error(message: &str) {
    use windows_sys::Win32::UI::WindowsAndMessaging::{MessageBoxW, MB_ICONERROR, MB_OK};
    unsafe {
        MessageBoxW(
            ptr::null_mut(),
            wide(OsStr::new(message)).as_ptr(),
            wide(OsStr::new("论文阅读器")).as_ptr(),
            MB_ICONERROR | MB_OK,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn quote_windows_paths() {
        let decode = |s: &str| String::from_utf16(&quoted(OsStr::new(s))).unwrap();
        assert_eq!(
            decode("D:\\目录 with space\\"),
            "\"D:\\目录 with space\\\\\""
        );
        assert_eq!(decode("a\"b"), "\"a\\\"b\"");
    }
}
