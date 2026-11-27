"""Cancel a real running request and a queued follower; no audio is published."""
import json
import time
from ace_gateway_probe import ROOT, call


def main():
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    request = {'request_id': 'cancel-running-' + stamp, 'kind': 'generate', 'model_id': 'ace-step-1.5-xl-turbo',
               'prompt': 'Instrumental acoustic piano trio with upright bass and gentle jazz drums.',
               'lyrics': '', 'instrumental': True, 'duration_seconds': 120, 'bpm': 120,
               'time_signature': '4/4', 'seed': 124}
    status, item = call('/jobs', request)
    assert status == 202, item
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status, item = call('/jobs/' + request['request_id'])
        if item['status'] == 'running':
            break
        if item['status'] in {'failed', 'ready', 'cancelled', 'interrupted'}:
            raise RuntimeError('Expected running state before cancellation: '+item['status'])
        time.sleep(.05)
    else:
        call('/jobs/'+request['request_id']+'/cancel', {})
        raise TimeoutError('Could not reach running state')
    queued = dict(request, request_id='cancel-queued-' + stamp)
    status, queued_item = call('/jobs', queued)
    assert status == 202 and queued_item['status'] == 'queued', queued_item
    status, queued_item = call('/jobs/'+queued['request_id']+'/cancel', {})
    assert status == 200 and queued_item['status'] == 'cancelled', queued_item
    started = time.monotonic()
    status, item = call('/jobs/'+request['request_id']+'/cancel', {})
    assert status == 200 and item['status'] in {'cancelling', 'cancelled'}, item
    while time.monotonic()-started < 60:
        status, item = call('/jobs/'+request['request_id'])
        if item['status'] == 'cancelled':
            break
        if item['status'] in {'failed', 'ready', 'interrupted'}:
            raise RuntimeError('Cancellation failed: '+item['status'])
        time.sleep(.1)
    else:
        raise TimeoutError('Cancellation did not finish within 60 seconds')
    report = {'utc': stamp, 'running_job': request['request_id'], 'running_cancelled': True,
              'queued_job': queued['request_id'], 'queued_cancelled': True,
              'cancellation_seconds': time.monotonic()-started}
    for job in (request, queued):
        status, _ = call('/jobs/'+job['request_id']+'/artifacts/audio.wav')
        assert status == 409, 'Cancelled artifact must not be downloadable'
    report['cancelled_downloads_rejected'] = True
    ROOT.joinpath('experiments', 'cancel-'+stamp+'.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__ == '__main__':
    main()
